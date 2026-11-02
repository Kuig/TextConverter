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

# Every entry runs convert.cmd, which calls "textconverter convert" and writes
# "<name>_converted<ext>" next to the source file. A target with choices opens a
# submenu whose "Default" is the CLI's own defaults.
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

# The choices of a submenu. Explorer sorts entries by key.
$DefaultChoice = @{ Key = "01default"; Verb = "Default" }
$NoImages = @{ Key = "02discard"; Verb = "No images"; Handling = "discard" }
$Transcribe = @{ Key = "03transcribe"; Verb = "Transcribe text"; Handling = "transcribe" }
$Describe = @{ Key = "04describe"; Verb = "Transcribe and describe"; Handling = "describe" }
$TextOnly = @{ Key = "05replace"; Verb = "Text only"; Handling = "replace" }
$WithText = @{ Key = "06append"; Verb = "Images with their text"; Handling = "append" }
$Raster = @{ Key = "07raster"; Verb = "Raster pages (AI)"; PdfMode = "raster" }
$MainContent = @{ Key = "08main"; Verb = "Main content"; Extract = $true }

$DocumentImages = @($NoImages, $Transcribe, $Describe, $TextOnly, $WithText)
# An image is the document, so it cannot be discarded, and the default transcribes it.
$ImageImages = @($Describe, $TextOnly, $WithText)
# Excel and CSV keep the tables only: what becomes of the images makes little difference.
$TableExtensions = @(".xlsx", ".csv")

# Targets with their choices: those about images, except for tables, and the others.
function Add-Choices($Targets, $Images, $Others = @()) {
    foreach ($Target in $Targets) {
        $Choices = @($Others)
        if ($TableExtensions -notcontains $Target.Ext) { $Choices = @($Images) + $Choices }
        Copy-Target $Target @{ Choices = $Choices }
    }
}

# HTML sources: HTML is a target too (it cleans a page up).
$HtmlTargets = Add-Choices (Get-Targets) $DocumentImages @($MainContent)
$ImageTargets = Add-Choices (Get-Targets) $ImageImages

# Define associations and subcommands
$Associations = [ordered]@{
    ".pdf" = Add-Choices (Get-Targets ".pdf") $DocumentImages @($Raster)
    ".md" = Add-Choices (Get-Targets ".md") $DocumentImages
    ".markdown" = Add-Choices (Get-Targets ".md") $DocumentImages
    ".tex" = Add-Choices (Get-Targets ".tex") $DocumentImages
    ".latex" = Add-Choices (Get-Targets ".tex") $DocumentImages
    ".html" = $HtmlTargets
    ".htm" = $HtmlTargets
    ".docx" = Add-Choices (Get-Targets ".docx") $DocumentImages
    ".pptx" = Add-Choices (Get-Targets ".pptx") $DocumentImages
    ".csv" = Get-Targets ".csv"
    ".tsv" = Get-Targets
    ".xlsx" = Get-Targets ".xlsx"
    ".json" = Get-Targets
    ".png" = $ImageTargets
    ".jpg" = $ImageTargets
    ".jpeg" = $ImageTargets
    ".gif" = $ImageTargets
    ".bmp" = $ImageTargets
    ".webp" = $ImageTargets
}

# The registry lines of an entry that runs a conversion: a key, its label, its command.
function Get-Entry([string]$Key, $Entry, [string]$Ext) {
    # Code detection works on a PDF's text layer; Markdown and LaTeX are already structured.
    $Options = @("--template", $Entry.Template)
    if ($Entry.Extract) { $Options += "--extract-html" }
    if ($Entry.Handling) { $Options += @("--image-handling", $Entry.Handling) }
    if ($Entry.PdfMode) { $Options += @("--pdf-mode", $Entry.PdfMode) }
    elseif ($Ext -eq ".pdf") { $Options += "--code-parsing" }
    $OptionString = $Options -join " "

    "`r`n[$Key]`r`n`"MUIVerb`"=`"$($Entry.Verb)`"`r`n" +
    "`r`n[$Key\command]`r`n" +
    '@="\"' + $EscapedCmdPath + '\" \"%1\" ' + $Entry.Ext + ' ' + $OptionString + '"' + "`r`n"
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
        $Key = "HKEY_CLASSES_ROOT\SystemFileAssociations\$Ext\shell\TextConverter\shell\$($Sub.Key)"
        $Choices = @($Sub.Choices)
        if ($Choices.Count -eq 0 -or $null -eq $Sub.Choices) {
            $RegisterContent += Get-Entry $Key $Sub $Ext
            continue
        }
        $RegisterContent += "`r`n[$Key]`r`n`"MUIVerb`"=`"$($Sub.Verb)`"`r`n`"SubCommands`"=`"`"`r`n"
        foreach ($Choice in @($DefaultChoice) + $Choices) {
            $RegisterContent += Get-Entry "$Key\shell\$($Choice.Key)" (Copy-Target $Sub $Choice) $Ext
        }
    }
}

# Output registry files as UTF-16 LE (Unicode) for native Windows compatibility
$RegisterPath = Join-Path $OutputDir "register.reg"
$UnregisterPath = Join-Path $OutputDir "unregister.reg"

$RegisterContent | Out-File -FilePath $RegisterPath -Encoding Unicode
$UnregisterContent | Out-File -FilePath $UnregisterPath -Encoding Unicode

Write-Host "Generated register.reg and unregister.reg successfully in:"
Write-Host "   $OutputDir"
