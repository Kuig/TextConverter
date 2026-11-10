param(
    # Where register.reg and unregister.reg are written.
    [string]$OutputDir = $PSScriptRoot
)

# Determine paths dynamically
$ScriptDir = $PSScriptRoot
$ProjectDir = (Get-Item $ScriptDir).Parent.FullName
$ExePath = Join-Path $ProjectDir ".venv\Scripts\textconverter.exe"
$CmdPath = Join-Path $ScriptDir "convert.cmd"
$GuiPath = Join-Path $ScriptDir "launch_gui.bat"

if (-not (Test-Path $ExePath)) {
    Write-Warning "$ExePath not found: create the .venv and install the project before using the menu."
}

# Every conversion entry runs convert.cmd, which calls "textconverter convert" with
# the CLI's own defaults and writes "<name>_converted<ext>" next to the source file.
# "Open with TextConverter" runs launch_gui.bat, which opens the GUI with the file as
# its source, for every other option.
$EscapedCmdPath = $CmdPath.Replace("\", "\\")
$EscapedGuiPath = $GuiPath.Replace("\", "\\")

# Explorer shows at most 16 entries of a menu, submenus included, and drops the rest
# without a word: the conversions are one flat list, the options are in the GUI.
$MaxEntries = 16

# Every target of the menu.
$Targets = @(
    [ordered]@{ Key="01md"; Verb="to Markdown (.md)"; Ext=".md"; Template="plain" }
    [ordered]@{ Key="02tex"; Verb="to LaTeX (.tex)"; Ext=".tex"; Template="plain" }
    [ordered]@{ Key="03html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain" }
    [ordered]@{ Key="04html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme" }
    [ordered]@{ Key="05html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme" }
    [ordered]@{ Key="06pdf"; Verb="to PDF (.pdf)"; Ext=".pdf"; Template="plain" }
    [ordered]@{ Key="07docx"; Verb="to Word (.docx)"; Ext=".docx"; Template="plain" }
    [ordered]@{ Key="08pptx"; Verb="to PowerPoint (.pptx)"; Ext=".pptx"; Template="plain" }
    [ordered]@{ Key="09xlsx"; Verb="to Excel (.xlsx)"; Ext=".xlsx"; Template="plain" }
    [ordered]@{ Key="10csv"; Verb="to CSV (.csv)"; Ext=".csv"; Template="plain" }
    [ordered]@{ Key="11aston"; Verb="to AST (.aston)"; Ext=".aston"; Template="plain" }
)

# The targets of a source: all of them, except the source's own format.
function Get-Targets([string]$Without = "") {
    @($Targets | Where-Object { $_.Ext -ne $Without })
}

# Define associations and subcommands. HTML is a target of HTML too (it cleans a page up).
$Associations = [ordered]@{
    ".pdf" = Get-Targets ".pdf"
    ".md" = Get-Targets ".md"
    ".markdown" = Get-Targets ".md"
    ".tex" = Get-Targets ".tex"
    ".latex" = Get-Targets ".tex"
    ".html" = Get-Targets
    ".htm" = Get-Targets
    ".docx" = Get-Targets ".docx"
    ".pptx" = Get-Targets ".pptx"
    ".csv" = Get-Targets ".csv"
    ".tsv" = Get-Targets
    ".xlsx" = Get-Targets ".xlsx"
    ".aston" = Get-Targets ".aston"
    ".png" = Get-Targets
    ".jpg" = Get-Targets
    ".jpeg" = Get-Targets
    ".gif" = Get-Targets
    ".bmp" = Get-Targets
    ".webp" = Get-Targets
}

# The registry lines of an entry that runs a conversion: a key, its label, its command.
function Get-Entry([string]$Key, $Entry, [string]$Ext) {
    # Code detection works on a PDF's text layer; Markdown and LaTeX are already structured.
    $Options = @("--template", $Entry.Template)
    if ($Ext -eq ".pdf") { $Options += "--code-parsing" }
    $OptionString = $Options -join " "

    "`r`n[$Key]`r`n`"MUIVerb`"=`"$($Entry.Verb)`"`r`n" +
    "`r`n[$Key\command]`r`n" +
    '@="\"' + $EscapedCmdPath + '\" \"%1\" ' + $Entry.Ext + ' ' + $OptionString + '"' + "`r`n"
}

# Generate register.reg
$RegisterContent = "Windows Registry Editor Version 5.00`r`n"
# Generate unregister.reg
$UnregisterContent = "Windows Registry Editor Version 5.00`r`n"

# The AST was read as .json up to 0.5.0.
foreach ($Ext in @(".json")) {
    $RegisterContent += "`r`n[-HKEY_CLASSES_ROOT\SystemFileAssociations\$Ext\shell\TextConverter]`r`n"
    $UnregisterContent += "`r`n[-HKEY_CLASSES_ROOT\SystemFileAssociations\$Ext\shell\TextConverter]`r`n"
}

foreach ($Ext in $Associations.Keys) {
    $Subcommands = $Associations[$Ext]
    if ($Subcommands.Count -gt $MaxEntries) {
        throw "$Ext has $($Subcommands.Count) targets: Explorer shows only the first $MaxEntries."
    }
    $Shell = "HKEY_CLASSES_ROOT\SystemFileAssociations\$Ext\shell"

    # Remove the entries of an earlier registration, then write the main entry for this extension
    $RegisterContent += "`r`n[-$Shell\TextConverter]`r`n"
    $RegisterContent += "`r`n[$Shell\TextConverter]`r`n"
    $RegisterContent += "`"MUIVerb`"=`"Convert with TextConverter...`"`r`n"
    $RegisterContent += "`"SubCommands`"=`"`"`r`n"
    foreach ($Sub in $Subcommands) {
        $RegisterContent += Get-Entry "$Shell\TextConverter\shell\$($Sub.Key)" $Sub $Ext
    }

    # The entry that opens the GUI on the file
    $RegisterContent += "`r`n[-$Shell\TextConverterGui]`r`n"
    $RegisterContent += "`r`n[$Shell\TextConverterGui]`r`n`"MUIVerb`"=`"Open with TextConverter`"`r`n"
    $RegisterContent += "`r`n[$Shell\TextConverterGui\command]`r`n"
    $RegisterContent += '@="\"' + $EscapedGuiPath + '\" \"%1\""' + "`r`n"

    # Write the unregister clean keys for this extension
    $UnregisterContent += "`r`n[-$Shell\TextConverter]`r`n"
    $UnregisterContent += "`r`n[-$Shell\TextConverterGui]`r`n"
}

# Output registry files as UTF-16 LE (Unicode) for native Windows compatibility
$RegisterPath = Join-Path $OutputDir "register.reg"
$UnregisterPath = Join-Path $OutputDir "unregister.reg"

$RegisterContent | Out-File -FilePath $RegisterPath -Encoding Unicode
$UnregisterContent | Out-File -FilePath $UnregisterPath -Encoding Unicode

Write-Host "Generated register.reg and unregister.reg successfully in:"
Write-Host "   $OutputDir"
