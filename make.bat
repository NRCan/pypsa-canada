@ECHO OFF

pushd %~dp0

REM Minimal make.bat for Sphinx documentation
IF "%SPHINXBUILD%" == "" (
    SET SPHINXBUILD=sphinx-build
)
SET SOURCEDIR=.
SET BUILDDIR=_build

IF "%1" == "" GOTO help

%SPHINXBUILD% -M %1 %SOURCEDIR% %BUILDDIR% %SPHINXOPTS%
GOTO end

:help
%SPHINXBUILD% -M help %SOURCEDIR% %BUILDDIR% %SPHINXOPTS%

:end
popd
