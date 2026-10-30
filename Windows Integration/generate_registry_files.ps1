# Determine paths dynamically
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = (Get-Item $ScriptDir).Parent.FullName
$ExePath = Join-Path $ProjectDir ".venv\Scripts\textconverter.exe"
$CmdPath = Join-Path $ScriptDir "convert.cmd"

if (-not (Test-Path $ExePath)) {
    Write-Warning "$ExePath not found: create the .venv and install the project before using the menu."
}

# Every entry runs convert.cmd, which calls "textconverter convert" with the
# CLI's own defaults and writes the result next to the source file.
$EscapedCmdPath = $CmdPath.Replace("\", "\\")

# Subcommands for image sources (and for JSON, which has the same targets):
# the image is transcribed or described by the AI models of config.json.
$ImageSubcommands = @(
    [ordered]@{ Key="01md"; Verb="to Markdown (.md)"; Ext=".md"; Template="plain"; Extract=$false }
    [ordered]@{ Key="02tex"; Verb="to LaTeX (.tex)"; Ext=".tex"; Template="plain"; Extract=$false }
    [ordered]@{ Key="03html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
    [ordered]@{ Key="04html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
    [ordered]@{ Key="05html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
    [ordered]@{ Key="06pdf"; Verb="to PDF (.pdf)"; Ext=".pdf"; Template="plain"; Extract=$false }
        [ordered]@{ Key="07docx"; Verb="to Word (.docx)"; Ext=".docx"; Template="plain"; Extract=$false }
        [ordered]@{ Key="08pptx"; Verb="to PowerPoint (.pptx)"; Ext=".pptx"; Template="plain"; Extract=$false }
)

# Define subcommands for PDF sources: text-layer conversions, then the same
# conversions in raster mode (pages rendered and transcribed by AI). No PDF
# target: the output would overwrite the source file.
$PdfTextSubcommands = @(
    [ordered]@{ Key="01md"; Verb="to Markdown (.md)"; Ext=".md"; Template="plain"; Extract=$false }
    [ordered]@{ Key="02tex"; Verb="to LaTeX (.tex)"; Ext=".tex"; Template="plain"; Extract=$false }
    [ordered]@{ Key="03html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
    [ordered]@{ Key="04html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
    [ordered]@{ Key="05html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
        [ordered]@{ Key="06docx"; Verb="to Word (.docx)"; Ext=".docx"; Template="plain"; Extract=$false }
        [ordered]@{ Key="07pptx"; Verb="to PowerPoint (.pptx)"; Ext=".pptx"; Template="plain"; Extract=$false }
)
# Explorer sorts subcommands by key, so the "r" prefix lists the raster ones last.
$PdfRasterSubcommands = foreach ($Sub in $PdfTextSubcommands) {
    $Copy = [ordered]@{} + $Sub
    $Copy.Key = "r" + $Sub.Key
    $Copy.Verb = $Sub.Verb + " (raster)"
    $Copy.PdfMode = "raster"
    $Copy
}

# Define associations and subcommands
$Associations = [ordered]@{
    ".pdf" = @($PdfTextSubcommands) + @($PdfRasterSubcommands)
    ".md" = @(
        [ordered]@{ Key="01tex"; Verb="to LaTeX (.tex)"; Ext=".tex"; Template="plain"; Extract=$false }
        [ordered]@{ Key="02html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
        [ordered]@{ Key="03html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
        [ordered]@{ Key="04html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
        [ordered]@{ Key="05pdf"; Verb="to PDF (.pdf)"; Ext=".pdf"; Template="plain"; Extract=$false }
        [ordered]@{ Key="06docx"; Verb="to Word (.docx)"; Ext=".docx"; Template="plain"; Extract=$false }
        [ordered]@{ Key="07pptx"; Verb="to PowerPoint (.pptx)"; Ext=".pptx"; Template="plain"; Extract=$false }
    )
    ".markdown" = @(
        [ordered]@{ Key="01tex"; Verb="to LaTeX (.tex)"; Ext=".tex"; Template="plain"; Extract=$false }
        [ordered]@{ Key="02html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
        [ordered]@{ Key="03html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
        [ordered]@{ Key="04html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
        [ordered]@{ Key="05pdf"; Verb="to PDF (.pdf)"; Ext=".pdf"; Template="plain"; Extract=$false }
        [ordered]@{ Key="06docx"; Verb="to Word (.docx)"; Ext=".docx"; Template="plain"; Extract=$false }
        [ordered]@{ Key="07pptx"; Verb="to PowerPoint (.pptx)"; Ext=".pptx"; Template="plain"; Extract=$false }
    )
    ".tex" = @(
        [ordered]@{ Key="01md"; Verb="to Markdown (.md)"; Ext=".md"; Template="plain"; Extract=$false }
        [ordered]@{ Key="02html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
        [ordered]@{ Key="03html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
        [ordered]@{ Key="04html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
        [ordered]@{ Key="05pdf"; Verb="to PDF (.pdf)"; Ext=".pdf"; Template="plain"; Extract=$false }
        [ordered]@{ Key="06docx"; Verb="to Word (.docx)"; Ext=".docx"; Template="plain"; Extract=$false }
        [ordered]@{ Key="07pptx"; Verb="to PowerPoint (.pptx)"; Ext=".pptx"; Template="plain"; Extract=$false }
    )
    ".latex" = @(
        [ordered]@{ Key="01md"; Verb="to Markdown (.md)"; Ext=".md"; Template="plain"; Extract=$false }
        [ordered]@{ Key="02html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
        [ordered]@{ Key="03html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
        [ordered]@{ Key="04html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
        [ordered]@{ Key="05pdf"; Verb="to PDF (.pdf)"; Ext=".pdf"; Template="plain"; Extract=$false }
        [ordered]@{ Key="06docx"; Verb="to Word (.docx)"; Ext=".docx"; Template="plain"; Extract=$false }
        [ordered]@{ Key="07pptx"; Verb="to PowerPoint (.pptx)"; Ext=".pptx"; Template="plain"; Extract=$false }
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
        [ordered]@{ Key="11pdf"; Verb="to PDF (.pdf)"; Ext=".pdf"; Template="plain"; Extract=$false }
        [ordered]@{ Key="13docx"; Verb="to Word (.docx)"; Ext=".docx"; Template="plain"; Extract=$false }
        [ordered]@{ Key="15pptx"; Verb="to PowerPoint (.pptx)"; Ext=".pptx"; Template="plain"; Extract=$false }
        [ordered]@{ Key="12pdf_main"; Verb="to PDF - main content (.pdf)"; Ext=".pdf"; Template="plain"; Extract=$true }
        [ordered]@{ Key="14docx_main"; Verb="to Word - main content (.docx)"; Ext=".docx"; Template="plain"; Extract=$true }
        [ordered]@{ Key="16pptx_main"; Verb="to PowerPoint - main content (.pptx)"; Ext=".pptx"; Template="plain"; Extract=$true }
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
        [ordered]@{ Key="11pdf"; Verb="to PDF (.pdf)"; Ext=".pdf"; Template="plain"; Extract=$false }
        [ordered]@{ Key="13docx"; Verb="to Word (.docx)"; Ext=".docx"; Template="plain"; Extract=$false }
        [ordered]@{ Key="15pptx"; Verb="to PowerPoint (.pptx)"; Ext=".pptx"; Template="plain"; Extract=$false }
        [ordered]@{ Key="12pdf_main"; Verb="to PDF - main content (.pdf)"; Ext=".pdf"; Template="plain"; Extract=$true }
        [ordered]@{ Key="14docx_main"; Verb="to Word - main content (.docx)"; Ext=".docx"; Template="plain"; Extract=$true }
        [ordered]@{ Key="16pptx_main"; Verb="to PowerPoint - main content (.pptx)"; Ext=".pptx"; Template="plain"; Extract=$true }
    )
    ".docx" = @(
        [ordered]@{ Key="01md"; Verb="to Markdown (.md)"; Ext=".md"; Template="plain"; Extract=$false }
        [ordered]@{ Key="02tex"; Verb="to LaTeX (.tex)"; Ext=".tex"; Template="plain"; Extract=$false }
        [ordered]@{ Key="03html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
        [ordered]@{ Key="04html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
        [ordered]@{ Key="05html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
        [ordered]@{ Key="06pdf"; Verb="to PDF (.pdf)"; Ext=".pdf"; Template="plain"; Extract=$false }
        [ordered]@{ Key="07pptx"; Verb="to PowerPoint (.pptx)"; Ext=".pptx"; Template="plain"; Extract=$false }
    )
    ".pptx" = @(
        [ordered]@{ Key="01md"; Verb="to Markdown (.md)"; Ext=".md"; Template="plain"; Extract=$false }
        [ordered]@{ Key="02tex"; Verb="to LaTeX (.tex)"; Ext=".tex"; Template="plain"; Extract=$false }
        [ordered]@{ Key="03html_plain"; Verb="to HTML (no theme)"; Ext=".html"; Template="plain"; Extract=$false }
        [ordered]@{ Key="04html_light"; Verb="to HTML (light theme)"; Ext=".html"; Template="light-theme"; Extract=$false }
        [ordered]@{ Key="05html_dark"; Verb="to HTML (dark theme)"; Ext=".html"; Template="dark-theme"; Extract=$false }
        [ordered]@{ Key="06pdf"; Verb="to PDF (.pdf)"; Ext=".pdf"; Template="plain"; Extract=$false }
        [ordered]@{ Key="07docx"; Verb="to Word (.docx)"; Ext=".docx"; Template="plain"; Extract=$false }
    )
    ".json" = $ImageSubcommands
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
$RegisterPath = Join-Path $ScriptDir "register.reg"
$UnregisterPath = Join-Path $ScriptDir "unregister.reg"

$RegisterContent | Out-File -FilePath $RegisterPath -Encoding Unicode
$UnregisterContent | Out-File -FilePath $UnregisterPath -Encoding Unicode

Write-Host "✅ Generated register.reg and unregister.reg successfully in:"
Write-Host "   $ScriptDir"
