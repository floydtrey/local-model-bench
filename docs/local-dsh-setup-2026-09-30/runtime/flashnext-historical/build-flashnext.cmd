@echo off
setlocal

set "ROOT=C:\AI\FlashNext-Lab"
set "REPO=%ROOT%\src\llama.cpp"
set "TOOLS=%ROOT%\tools\.venv\Scripts"
set "BUILD=%ROOT%\build\cuda-13.3"

set "STEP=Initialize Microsoft x64 compiler"
echo.
echo === %STEP% ===
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if not "%errorlevel%"=="0" goto fail

set "CUDA_PATH=%ROOT%\tools\cuda-13.3"
set "CUDA_PATH_V13_3=%CUDA_PATH%"
set "CUDACXX=%CUDA_PATH%\bin\nvcc.exe"
set "PATH=%TOOLS%;%CUDA_PATH%\bin;%CUDA_PATH%\bin\x64;%PATH%"
set "TEMP=%ROOT%\tools\build-temp"
set "TMP=%TEMP%"
set "CUDA_CACHE_PATH=%ROOT%\cache\cuda"
set "HF_HUB_OFFLINE=1"

echo Local tools: %TOOLS%
echo Local CUDA:  %CUDA_PATH%

where cl.exe
if not "%errorlevel%"=="0" goto fail
where rc.exe
if not "%errorlevel%"=="0" goto fail

set "STEP=Configure CUDA Release build"
echo.
echo === %STEP% ===

"%TOOLS%\cmake.exe" -S "%REPO%" -B "%BUILD%" -G Ninja ^
  "-DCMAKE_BUILD_TYPE=Release" ^
  "-DCMAKE_MAKE_PROGRAM=%TOOLS%\ninja.exe" ^
  "-DCMAKE_C_COMPILER=cl.exe" ^
  "-DCMAKE_CXX_COMPILER=cl.exe" ^
  "-DCMAKE_CUDA_COMPILER=%CUDA_PATH%\bin\nvcc.exe" ^
  "-DCUDAToolkit_ROOT=%CUDA_PATH%" ^
  "-DCMAKE_CUDA_ARCHITECTURES=120a-real" ^
  "-DGGML_NATIVE=ON" ^
  "-DGGML_CUDA=ON" ^
  "-DGGML_RPC=OFF" ^
  "-DGGML_CCACHE=OFF" ^
  "-DGGML_CUDA_CUB_3DOT2=OFF" ^
  "-DGGML_OPENMP_FETCH=OFF" ^
  "-DLLAMA_BUILD_COMMON=ON" ^
  "-DLLAMA_BUILD_TOOLS=ON" ^
  "-DLLAMA_BUILD_SERVER=ON" ^
  "-DLLAMA_BUILD_APP=OFF" ^
  "-DLLAMA_BUILD_TESTS=OFF" ^
  "-DLLAMA_BUILD_EXAMPLES=OFF" ^
  "-DLLAMA_BUILD_UI=OFF" ^
  "-DLLAMA_USE_PREBUILT_UI=OFF" ^
  "-DLLAMA_OPENSSL=OFF" ^
  "-DLLAMA_SUBPROCESS=OFF" ^
  "-DLLAMA_LLGUIDANCE=OFF"
if not "%errorlevel%"=="0" goto fail

set "STEP=Compile selected tools"
echo.
echo === %STEP% ===

"%TOOLS%\cmake.exe" --build "%BUILD%" --parallel 4 --target llama-server llama-cli llama-bench llama-moe-trace
if not "%errorlevel%"=="0" goto fail

echo.
echo === BUILD SUMMARY ===

set "STEP=Check executable startup"
"%BUILD%\bin\llama-server.exe" --version
if not "%errorlevel%"=="0" goto fail

set "STEP=Check CUDA device detection"
"%BUILD%\bin\llama-server.exe" --list-devices > "%ROOT%\logs\flashnext-devices.txt" 2>&1
if not "%errorlevel%"=="0" goto fail
type "%ROOT%\logs\flashnext-devices.txt"

findstr /I /C:"5060" "%ROOT%\logs\flashnext-devices.txt" >nul
if not "%errorlevel%"=="0" goto fail

set "STEP=Check expert-cache command options"
"%BUILD%\bin\llama-server.exe" --help > "%ROOT%\logs\flashnext-server-help.txt" 2>&1
if not "%errorlevel%"=="0" goto fail

findstr /L /C:"--moe-cache-profile" "%ROOT%\logs\flashnext-server-help.txt"
if not "%errorlevel%"=="0" goto fail
findstr /L /C:"--moe-cache-slots" "%ROOT%\logs\flashnext-server-help.txt"
if not "%errorlevel%"=="0" goto fail

echo.
echo === Selected build settings ===
findstr /B /C:"GGML_CUDA:BOOL=" /C:"GGML_RPC:BOOL=" /C:"LLAMA_SUBPROCESS:BOOL=" /C:"LLAMA_BUILD_UI:BOOL=" /C:"LLAMA_USE_PREBUILT_UI:BOOL=" "%BUILD%\CMakeCache.txt"
if not "%errorlevel%"=="0" goto fail

echo.
echo BUILD AND STARTUP CHECKS PASSED
echo Binaries: %BUILD%\bin
echo No model loaded. No listening server started.
exit /b 0

:fail
echo.
echo FAILED DURING: %STEP%
echo Stop here and inspect the build log.
exit /b 1

