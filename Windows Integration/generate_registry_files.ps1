param(
    # Where register.reg and unregister.reg are written.
    [string]$OutputDir = $PSScriptRoot
)

# Determine paths dynamically
$ScriptDir = $PSScriptRoot
$ProjectDir = (Get-Item $ScriptDir).Parent.FullName
$ExePath = Join-Path $ProjectDir ".venv\Scripts\textconverter.exe"
$CmdPath = Join-Path $ScriptDir "convert.cmd"

if (-not (Test-Path $ExePath)) {
    Write-Warning "$ExePath not found: create the .venv and install the project before using the menu."
}

# Every entry runs convert.cmd, which calls "textconverter convert" with the
# CLI's own defaults and writes "<name>_converted<ext>" next to the source file.
$EscapedCmdPath = $CmdPath.Replace("\", "\\")

# Every target of the menu. JSON is left out on purpose: it is the AST, for
# debugging or for reusing a parsed document, and is reached through the CLI.
$Targets = @(
    [ordered]@{ Key="01md"; Verb="to Markdown (.md)"; Ext=".md"; Template="plain"; Extract=$false }
    [ordered]@{ Key="02tex"; Verb="to LaTeX (.tex)"; Ext=".tex"; Template="plain"; Extract=$false }
    [ordered]@{ Key="03html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
    [ordered]@{ Key="04html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
    [ordered]@{ Key="05html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
    [ordered]@{ Key="06pdf"; Verb="to PDF (.pdf)"; Ext=".pdf"; Template="plain"; Extract=$false }
    [ordered]@{ Key="07docx"; Verb="to Word (.docx)"; Ext=".docx"; Template="plain"; Extract=$false }
    [ordered]@{ Key="08pptx"; Verb="to PowerPoint (.pptx)"; Ext=".pptx"; Template="plain"; Extract=$false }
    [ordered]@{ Key="09xlsx"; Verb="to Excel (.xlsx)"; Ext=".xlsx"; Template="plain"; Extract=$false }
    [ordered]@{ Key="10csv"; Verb="to CSV (.csv)"; Ext=".csv"; Template="plain"; Extract=$false }
)

# The targets of a source: all of them, except the source's own format.
function Get-Targets([string]$Without = "") {
    @($Targets | Where-Object { $_.Ext -ne $Without })
}

# A copy of a target with some of its fields changed.
function Copy-Target($Target, [hashtable]$Changes) {
    $Copy = [ordered]@{}
    foreach ($Field in $Target.Keys) { $Copy[$Field] = $Target[$Field] }
    foreach ($Field in $Changes.Keys) { $Copy[$Field] = $Changes[$Field] }
    $Copy
}

# PDF sources: text-layer conversions, then the same ones in raster mode (pages
# rendered and transcribed by AI). Explorer sorts entries by key, so the "r"
# prefix lists the raster ones last.
$PdfTargets = Get-Targets ".pdf"
$PdfRasterTargets = foreach ($Target in $PdfTargets) {
    Copy-Target $Target @{ Key = "r" + $Target.Key; Verb = $Target.Verb + " (raster)"; PdfMode = "raster" }
}

# HTML sources: HTML is a target too (it cleans a page up), and each target
# also comes on the main content alone.
$HtmlTargets = foreach ($Target in Get-Targets) {
    $Target
    Copy-Target $Target @{ Key = $Target.Key + "_main"; Verb = $Target.Verb + " - main content"; Extract = $true }
}

# Define associations and subcommands
$Associations = [ordered]@{
    ".pdf" = @($PdfTargets) + @($PdfRasterTargets)
    ".md" = Get-Targets ".md"
    ".markdown" = Get-Targets ".md"
    ".tex" = Get-Targets ".tex"
    ".latex" = Get-Targets ".tex"
    ".html" = $HtmlTargets
    ".htm" = $HtmlTargets
    ".docx" = Get-Targets ".docx"
    ".pptx" = Get-Targets ".pptx"
    ".csv" = Get-Targets ".csv"
    ".tsv" = Get-Targets
    ".xlsx" = Get-Targets ".xlsx"
    ".json" = Get-Targets
    ".png" = Get-Targets
    ".jpg" = Get-Targets
    ".jpeg" = Get-Targets
    ".gif" = Get-Targets
    ".bmp" = Get-Targets
    ".webp" = Get-Targets
}

# Generate register.reg
$RegisterContent = "Windows Registry Editor Version 5.00`r`n"
# Generate unregister.reg
$UnregisterContent = "Windows Registry Editor Version 5.00`r`n"

foreach ($Ext in $Associations.Keys) {
    $Subcommands = $Associations[$Ext]

    # Remove the entries of an earlier registration, then write the main entry for this extension
    $RegisterContent += "`r`n[-HKEY_CLASSES_ROOT\SystemFileAssociations\$Ext\shell\TextConverter]`r`n"
    $RegisterContent += "`r`n[HKEY_CLASSES_ROOT\SystemFileAssociations\$Ext\shell\TextConverter]`r`n"
    $RegisterContent += "`"MUIVerb`"=generic:`"Convert with TextConverter...`"`r`n".Replace("generic:", "") # escape string value quotes cleanly
    $RegisterContent += "`"SubCommands`"=generic:`"`"`r`n".Replace("generic:", "")

    # Write the unregister clean key for this extension
    $UnregisterContent += "`r`n[-HKEY_CLASSES_ROOT\SystemFileAssociations\$Ext\shell\TextConverter]`r`n"

    foreach ($Sub in $Subcommands) {
        $Key = $Sub.Key
        $Verb = $Sub.Verb
        $TargetExt = $Sub.Ext
        # textconverter convert options for this entry. Code detection works
        # on a PDF's text layer; Markdown and LaTeX are already structured.
        $Options = @("--template", $Sub.Template)
        if ($Sub.Extract) { $Options += "--extract-html" }
        if ($Sub.PdfMode) { $Options += @("--pdf-mode", $Sub.PdfMode) }
        elseif ($Ext -eq ".pdf") { $Options += "--code-parsing" }
        $OptionString = $Options -join " "

        $RegisterContent += "`r`n[HKEY_CLASSES_ROOT\SystemFileAssociations\$Ext\shell\TextConverter\shell\$Key]`r`n"
        $RegisterContent += "`"MUIVerb`"=generic:`"$Verb`"`r`n".Replace("generic:", "")

        $RegisterContent += "`r`n[HKEY_CLASSES_ROOT\SystemFileAssociations\$Ext\shell\TextConverter\shell\$Key\command]`r`n"
        $RegisterContent += '@="\"' + $EscapedCmdPath + '\" \"%1\" ' + $TargetExt + ' ' + $OptionString + '"' + "`r`n"
    }
}

# Output registry files as UTF-16 LE (Unicode) for native Windows compatibility
$RegisterPath = Join-Path $OutputDir "register.reg"
$UnregisterPath = Join-Path $OutputDir "unregister.reg"

$RegisterContent | Out-File -FilePath $RegisterPath -Encoding Unicode
$UnregisterContent | Out-File -FilePath $UnregisterPath -Encoding Unicode

Write-Host "Generated register.reg and unregister.reg successfully in:"
Write-Host "   $OutputDir"
