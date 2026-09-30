@echo off
setlocal
rem Reuse the established FlashNext-Lab runtime and local CUDA environment.
set "ROOT=C:\AI\FlashNext-Lab"
set "BIN=%ROOT%\build\cuda-13.3\bin"
set "CUDA_PATH=%ROOT%\tools\cuda-13.3"
set "PATH=%BIN%;%CUDA_PATH%\bin;%CUDA_PATH%\bin\x64;%PATH%"
set "CUDA_CACHE_PATH=%ROOT%\cache\cuda"
set "HF_HOME=%ROOT%\cache\huggingface"
set "HF_HUB_OFFLINE=1"
set "HF_HUB_DISABLE_TELEMETRY=1"
set "HF_TOKEN="
set "GGML_CUDA_REGISTER_HOST=1"
set "GGML_SCHED_PREFETCH_EXPERTS="
set "GGML_MOE_CACHE_PROFILE="
set "GGML_MOE_CACHE_SLOTS="
set "LLAMA_ARG_MOE_CACHE_PROFILE="
set "LLAMA_ARG_MOE_CACHE_SLOTS="
set "MOE_TRACE_OUT="
"%BIN%\llama-server.exe" ^
  -m "%ROOT%\models\Qwen3.8-Flash-Next\UD-IQ3_XXS\Qwen3.8-Flash-Next-UD-IQ3_XXS-00001-of-00003.gguf" ^
  --offline --load-mode mmap --lazy-mode on ^
  -ngl 99 -ncmoe 99 -fa on -ctk f16 -ctv f16 ^
  -t 8 -b 256 -ub 128 --no-sched-async-cpu ^
  -c 8192 -np 1 --no-context-shift ^
  --host 127.0.0.1 --port 8080 --alias flashnext-iq3 ^
  --jinja --reasoning auto --reasoning-format deepseek --metrics
exit /b %ERRORLEVEL%
