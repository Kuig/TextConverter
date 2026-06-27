# Determine paths dynamically
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = (Get-Item $ScriptDir).Parent.FullName
$PythonPath = Join-Path $ProjectDir ".venv\Scripts\python.exe"

# Format paths for Windows Registry and Python
$EscapedPythonPath = $PythonPath.Replace("\", "\\")
$PythonProjectDir = $ProjectDir.Replace("\", "/")

# Define subcommands for supported image types
$ImageSubcommands = @(
    [ordered]@{ Key="01md"; Verb="to Markdown (.md)"; Ext=".md"; Template="plain"; Extract=$false; ImageHandling="describe" }
    [ordered]@{ Key="02tex"; Verb="to LaTeX (.tex)"; Ext=".tex"; Template="plain"; Extract=$false; ImageHandling="describe" }
    [ordered]@{ Key="03html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false; ImageHandling="describe" }
    [ordered]@{ Key="04html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false; ImageHandling="describe" }
    [ordered]@{ Key="05html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false; ImageHandling="describe" }
)

# Define associations and subcommands
$Associations = [ordered]@{
    ".pdf" = @(
        [ordered]@{ Key="01md"; Verb="to Markdown (.md)"; Ext=".md"; Template="plain"; Extract=$false }
        [ordered]@{ Key="02tex"; Verb="to LaTeX (.tex)"; Ext=".tex"; Template="plain"; Extract=$false }
        [ordered]@{ Key="03html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
        [ordered]@{ Key="04html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
        [ordered]@{ Key="05html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
    )
    ".md" = @(
        [ordered]@{ Key="01tex"; Verb="to LaTeX (.tex)"; Ext=".tex"; Template="plain"; Extract=$false }
        [ordered]@{ Key="02html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
        [ordered]@{ Key="03html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
        [ordered]@{ Key="04html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
    )
    ".markdown" = @(
        [ordered]@{ Key="01tex"; Verb="to LaTeX (.tex)"; Ext=".tex"; Template="plain"; Extract=$false }
        [ordered]@{ Key="02html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
        [ordered]@{ Key="03html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
        [ordered]@{ Key="04html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
    )
    ".tex" = @(
        [ordered]@{ Key="01md"; Verb="to Markdown (.md)"; Ext=".md"; Template="plain"; Extract=$false }
        [ordered]@{ Key="02html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
        [ordered]@{ Key="03html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
        [ordered]@{ Key="04html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
    )
    ".latex" = @(
        [ordered]@{ Key="01md"; Verb="to Markdown (.md)"; Ext=".md"; Template="plain"; Extract=$false }
        [ordered]@{ Key="02html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
        [ordered]@{ Key="03html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
        [ordered]@{ Key="04html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
    )
    ".html" = @(
        [ordered]@{ Key="01md"; Verb="to Markdown (.md)"; Ext=".md"; Template="plain"; Extract=$false }
        [ordered]@{ Key="02md_main"; Verb="to Markdown - main content (.md)"; Ext=".md"; Template="plain"; Extract=$true }
        [ordered]@{ Key="03tex"; Verb="to LaTeX (.tex)"; Ext=".tex"; Template="plain"; Extract=$false }
        [ordered]@{ Key="04tex_main"; Verb="to LaTeX - main content (.tex)"; Ext=".tex"; Template="plain"; Extract=$true }
        [ordered]@{ Key="05html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
        [ordered]@{ Key="06html_plain_main"; Verb="to HTML (no theme) - main content"; Ext=".html"; Template="plain"; Extract=$true }
        [ordered]@{ Key="07html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
        [ordered]@{ Key="08html_light_main"; Verb="to HTML (light theme) - main content"; Ext=".html"; Template="light-theme"; Extract=$true }
        [ordered]@{ Key="09html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
        [ordered]@{ Key="10html_dark_main"; Verb="to HTML (dark theme) - main content"; Ext=".html"; Template="dark-theme"; Extract=$true }
    )
    ".htm" = @(
        [ordered]@{ Key="01md"; Verb="to Markdown (.md)"; Ext=".md"; Template="plain"; Extract=$false }
        [ordered]@{ Key="02md_main"; Verb="to Markdown - main content (.md)"; Ext=".md"; Template="plain"; Extract=$true }
        [ordered]@{ Key="03tex"; Verb="to LaTeX (.tex)"; Ext=".tex"; Template="plain"; Extract=$false }
        [ordered]@{ Key="04tex_main"; Verb="to LaTeX - main content (.tex)"; Ext=".tex"; Template="plain"; Extract=$true }
        [ordered]@{ Key="05html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
        [ordered]@{ Key="06html_plain_main"; Verb="to HTML (no theme) - main content"; Ext=".html"; Template="plain"; Extract=$true }
        [ordered]@{ Key="07html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
        [ordered]@{ Key="08html_light_main"; Verb="to HTML (light theme) - main content"; Ext=".html"; Template="light-theme"; Extract=$true }
        [ordered]@{ Key="09html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
        [ordered]@{ Key="10html_dark_main"; Verb="to HTML (dark theme) - main content"; Ext=".html"; Template="dark-theme"; Extract=$true }
    )
    ".png"  = $ImageSubcommands
    ".jpg"  = $ImageSubcommands
    ".jpeg" = $ImageSubcommands
    ".gif"  = $ImageSubcommands
    ".bmp"  = $ImageSubcommands
    ".webp" = $ImageSubcommands
}

# Generate register.reg
$RegisterContent = "Windows Registry Editor Version 5.00`r`n"
# Generate unregister.reg
$UnregisterContent = "Windows Registry Editor Version 5.00`r`n"

foreach ($Ext in $Associations.Keys) {
    $Subcommands = $Associations[$Ext]
    
    # Write the main entry for this extension
    $RegisterContent += "`r`n[HKEY_CLASSES_ROOT\SystemFileAssociations\$Ext\shell\TextConverter]`r`n"
    $RegisterContent += "`"MUIVerb`"=generic:`"Convert with TextConverter...`"`r`n".Replace("generic:", "") # escape string value quotes cleanly
    $RegisterContent += "`"SubCommands`"=generic:`"`"`r`n".Replace("generic:", "")

    # Write the unregister clean key for this extension
    $UnregisterContent += "`r`n[-HKEY_CLASSES_ROOT\SystemFileAssociations\$Ext\shell\TextConverter]`r`n"
    
    foreach ($Sub in $Subcommands) {
        $Key = $Sub.Key
        $Verb = $Sub.Verb
        $TargetExt = $Sub.Ext
        $Template = $Sub.Template
        $Extract = if ($Sub.Extract) { "True" } else { "False" }
        $ImgHandling = if ($Sub.ImageHandling) { $Sub.ImageHandling } else { "link" }
        
        # Construct the python one-liner command
        $pyCode = "import sys, pathlib; sys.path.append('$PythonProjectDir'); from textconverter.api import save_to_file; src=pathlib.Path(sys.argv[1]); out=src.with_suffix('$TargetExt'); save_to_file(str(src), str(out), template='$Template', code_parsing=True, image_handling='$ImgHandling', extract_html=$Extract)"
        
        $RegisterContent += "`r`n[HKEY_CLASSES_ROOT\SystemFileAssociations\$Ext\shell\TextConverter\shell\$Key]`r`n"
        $RegisterContent += "`"MUIVerb`"=generic:`"$Verb`"`r`n".Replace("generic:", "")
        
        $RegisterContent += "`r`n[HKEY_CLASSES_ROOT\SystemFileAssociations\$Ext\shell\TextConverter\shell\$Key\command]`r`n"
        $RegisterContent += '@="\"' + $EscapedPythonPath + '\" -c \"' + $pyCode + '\" \"%1\""' + "`r`n"
    }
}

# Output registry files as UTF-16 LE (Unicode) for native Windows compatibility
$RegisterPath = Join-Path $ScriptDir "register.reg"
$UnregisterPath = Join-Path $ScriptDir "unregister.reg"

$RegisterContent | Out-File -FilePath $RegisterPath -Encoding Unicode
$UnregisterContent | Out-File -FilePath $UnregisterPath -Encoding Unicode

Write-Host "✅ Generated register.reg and unregister.reg successfully in:"
Write-Host "   $ScriptDir"
