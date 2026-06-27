# Basic templating system

PLAIN_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Document</title>
</head>
<body>
{{content}}
</body>
</html>"""

# A minimalistic styled template
PRETTY_LIGHT_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Document</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    line-height: 1.6;
    color: #333;
    max-width: 800px;
    margin: 0 auto;
    padding: 2rem;
}
h1, h2, h3, h4, h5, h6 { margin-top: 1.5em; margin-bottom: 0.5em; font-weight: 600; }
a { color: #0366d6; text-decoration: none; }
a:hover { text-decoration: underline; }
pre, code { font-family: SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace; background-color: #f6f8fa; border-radius: 3px; }
pre { padding: 16px; overflow: auto; line-height: 1.45; }
code { padding: 0.2em 0.4em; font-size: 85%; }
table { border-collapse: collapse; width: 100%; margin-bottom: 1em; }
th, td { padding: 6px 13px; border: 1px solid #dfe2e5; }
tr:nth-child(even) { background-color: #f6f8fa; }
img { max-width: 100%; box-sizing: content-box; }
blockquote {
    padding: 0 1em;
    color: #6a737d;
    border-left: 0.25em solid #dfe2e5;
    margin: 1.5em 0;
}
hr {
    height: 0.25em;
    padding: 0;
    margin: 24px 0;
    background-color: #dfe2e5;
    border: 0;
}
blockquote.alert {
    padding: 12px 16px;
    border-left: 4px solid;
    margin: 1.5em 0;
    border-radius: 6px;
    background-color: #f6f8fa;
    color: inherit;
}
blockquote.alert-note { border-left-color: #0969da; }
blockquote.alert-tip { border-left-color: #1a7f37; }
blockquote.alert-important { border-left-color: #8250df; }
blockquote.alert-warning { border-left-color: #9a6700; }
blockquote.alert-caution { border-left-color: #d1242f; }
.alert-title {
    font-weight: 600;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
    text-transform: uppercase;
    font-size: 85%;
}
</style>
</head>
<body>
{{content}}
</body>
</html>"""

PRETTY_DARK_TEMPLATE = PRETTY_LIGHT_TEMPLATE.replace(
    'color: #333;', 'color: #c9d1d9;'
).replace(
    'background-color: #f6f8fa;', 'background-color: #161b22;'
).replace(
    'border: 1px solid #dfe2e5;', 'border: 1px solid #30363d;'
).replace(
    'border-left: 0.25em solid #dfe2e5;', 'border-left: 0.25em solid #30363d;'
).replace(
    'background-color: #dfe2e5;', 'background-color: #30363d;'
).replace(
    '#0969da', '#2f81f7'
).replace(
    '#1a7f37', '#3fb950'
).replace(
    '#8250df', '#bc8cff'
).replace(
    '#9a6700', '#d29922'
).replace(
    '#d1242f', '#f85149'
).replace(
    '<body>', '<body style="background-color: #0d1117;">'
)

def get_template(name: str) -> str:
    if name == 'light-theme' or name == 'pretty':
        return PRETTY_LIGHT_TEMPLATE
    elif name == 'dark-theme':
        return PRETTY_DARK_TEMPLATE
    return PLAIN_TEMPLATE
