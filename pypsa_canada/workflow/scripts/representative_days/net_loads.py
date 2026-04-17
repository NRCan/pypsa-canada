import os


def net_load_calculation(n, provinces=None, with_hydro=False, save_file=False, filepath="./"):
    """
    The net_load_v1.py aggregates the loads in NB, NS and PEI, identifies the wind and solar
    generation from these provinces, and subtracts the aggregated load by the aggregated generation.
    The output file from this script is used as input in rep_days_kmedoid_v1.py and rep_days_OPT_v1.py.
    The net_load_v2.py is similar to net_load_v1.py, but also subtract must-run hydro from the aggregated load
    #TODO to be redone

    Parameters
    ----------
    n : _type_
        _description_
    provinces : list, optional
        List of provinces to include in the calculation, by default None (excludes QC)
    with_hydro : bool, optional
        include hydro within the carrier selected, by default False
    save_file : bool, optional
        save intermediary csv file, by default False

    Returns
    -------
    pd.DataFrame
        _description_
    """
    # Load generators.csv
    # generators_df = pd.read_csv('generators.csv')
    generators_df = n.df("Generator")

    # Map provinces from buses
    generators_df['province'] = generators_df['bus'].map(n.buses['province'])

    # print(generators_df)
    # Filter rows with "carrier" equal to "wind" or "solar PV" and pnom not equal to 0
    if with_hydro:
        carrier_list = ["wind", "solar PV", "hydro"]
    else:
        carrier_list = ["wind", "solar PV"]

    filtered_generators_df = generators_df[
        (generators_df["carrier"].isin(carrier_list)) & (generators_df["p_nom"] != 0)
    ]

    # Filter by provinces if specified
    if provinces is not None:
        filtered_generators_df = filtered_generators_df[
            filtered_generators_df["province"].isin(provinces)
        ]
    # print(filtered_generators_df)
    # Load generators-p_max_pu.csv
    # p_max_pu_df = pd.read_csv('generators-p_max_pu.csv')
    p_max_pu_df = n.generators_t.p_max_pu.copy()

    # Filter columns based on the names obtained from the first file
    selected_names = filtered_generators_df.index
    # print(selected_names)
    selected_columns = p_max_pu_df.loc[:, selected_names]

    # Multiply selected columns by corresponding pnom
    for name in selected_names:
        selected_columns[name] *= filtered_generators_df[
            filtered_generators_df.index == name
        ]["p_nom"].values[0]

    # Sum up the columns
    RES_pow = selected_columns.sum(axis=1)

    # Load loads-p_set.csv
    # loads_p_set_df = pd.read_csv('loads-p_set.csv')
    loads_p_set_df = n.loads_t.p_set.copy()
    if loads_p_set_df.shape[0] > 8760:
        loads_p_set_df = loads_p_set_df.iloc[0:8760, :]
    # TODO not sure if really useful anymore now
    # Remove unnamed columns
    loads_p_set_df = loads_p_set_df.loc[
        :, ~loads_p_set_df.columns.str.contains("^Unnamed")
    ]

    # Map provinces from buses to loads
    load_prov_df = n.c["Load"].static.copy()
    load_prov_df['province'] = load_prov_df['bus'].map(n.buses['province'])

    # Filter loads by provinces
    if provinces is not None:
        # Get load columns for specified provinces
        load_columns = load_prov_df[load_prov_df['province'].isin(provinces)].index
        summed_loads_rows = loads_p_set_df[load_columns].sum(axis=1)
    else:
        # Exclude the "QC" column from the sum (original behavior)
        # summed_loads_rows = loads_p_set_df.drop(columns=['QC_a']).sum(axis=1)
        load_columns = load_prov_df[~load_prov_df['province'].str.contains("QC", na=False)].index
        summed_loads_rows = loads_p_set_df[load_columns].sum(axis=1)

    # To not exclude "QC"
    # summed_loads_rows = loads_p_set_df.loc[:, :].values.sum(axis=1)

    # Net load
    net_load = summed_loads_rows - RES_pow

    try:
        os.makedirs(filepath)
    except OSError:
        print("Folder exist skipping step")

    filename_csv = "net_load.csv"

    # Save the result to a CSV file
    if save_file:
        net_load.to_csv(f"{filepath}{filename_csv}", index=False)

    return net_load
