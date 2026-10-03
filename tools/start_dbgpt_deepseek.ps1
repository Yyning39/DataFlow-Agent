param(
    [string]$Model = "deepseek-v4-flash",
    [string]$ApiBase = "https://api.deepseek.com/v1",
    [string]$VersionComparisonFile = "",
    [ValidateSet("true", "false")]
    [string]$SchemaHybrid = "true"
)

# Keep model/runtime settings in one repeatable command. The DeepSeek adapter
# requires a real key; do not point the main service at tools/local_openai_proxy.py
# because that bridge forwards back to port 5670 and would create a request loop.
$env:DBGPT_HOME = "D:\1ALL\DB-GPT\requirement\dbgpt-home"
$env:LLM_MODEL_NAME = $Model
$env:LLM_MODEL_PROVIDER = "proxy/deepseek"
$env:OPENAI_API_BASE = $ApiBase
$env:DEEPSEEK_API_BASE = $ApiBase
$env:DEEPSEEK_API_KEY = if ($env:DEEPSEEK_API_KEY) { $env:DEEPSEEK_API_KEY } else { throw "请先设置 DEEPSEEK_API_KEY" }
$env:DEEPSEEK_MODEL_VERSION = $Model
$env:DBGPT_SEMANTICS_DIR = (Resolve-Path (Join-Path $PSScriptRoot "..\configs\semantics")).Path
$env:DBGPT_SCHEMA_HYBRID = $SchemaHybrid
# Versioned, dependency-free schema index; generated cache only, never source
# data or database files. Keeping it under D: avoids consuming C: space.
$env:DBGPT_SCHEMA_INDEX_DIR = "D:\1ALL\DB-GPT\requirement\dbgpt-home\schema_index\v9"
$env:EMBEDDING_MODEL_PROVIDER = "proxy/openai"
$env:EMBEDDING_MODEL_NAME = "text-embedding-3-small"
$env:EMBEDDING_MODEL_API_URL = "$ApiBase/embeddings"
$env:OPENAI_API_KEY = if ($env:OPENAI_API_KEY) { $env:OPENAI_API_KEY } else { $env:DEEPSEEK_API_KEY }
if ([string]::IsNullOrWhiteSpace($VersionComparisonFile)) {
    $defaultComparison = Join-Path $PSScriptRoot "..\docs\baseline\bird_v2_v3_v4_final_comparison.json"
    if (Test-Path $defaultComparison) {
        $VersionComparisonFile = (Resolve-Path $defaultComparison).Path
    }
}
if (-not [string]::IsNullOrWhiteSpace($VersionComparisonFile)) {
    $env:DBGPT_VERSION_COMPARISON_FILE = $VersionComparisonFile
} else {
    Remove-Item Env:DBGPT_VERSION_COMPARISON_FILE -ErrorAction SilentlyContinue
}

& "$PSScriptRoot\..\.venv\Scripts\dbgpt.exe" start webserver
