# Sample MD File

> [!IMPORTANT]
> This document is a sample MD file with some text.

---

## 1. Title

### 1.1 Subsection

Next thing is a **table**.

| Col One | Col Two |
|---|---|
| pippo | `foo.bar` |
| pluto | _bob_ |


List:

- Looks like
- This list is
- Not recognized.

### 1.2 tree example, very good

```
<ProjectRoot>/
├── <entry_point>.py          # Single entry point (snake_case)
├── core/                     # Business logic modules
│   ├── logger.py             # Unified logging (see §8)
│   └── ...                   # Domain-specific modules
├── gui/
│   └── app.py                # Streamlit web interface (see §2.5)
├── config.json               # Application configuration (see §4)
├── secrets.json              # API keys — MUST be in .gitignore (see §4)
├── requirements.txt          # Pinned dependencies (see §10)
├── README.md                 # English. Sections: Overview, Install, Usage, Config
├── .venv/                    # Isolated virtual environment — MUST be in .gitignore
└── .gitignore
```

### 2.4 A mess

**Both not list and weird code:**

- The list starts here.
- This element has code:

```python
# In the entry point (e.g., drytext.py)
elif args.command == "gui":
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "streamlit", "run", "gui/app.py"])
```

- Somehow breaks things `look at this` weird, innit? `uh?`.
- Here final text.

---

### 3.3 This list is correct

- All **code symbols** (function names, variable names, class names): **English**.
- All **comments and docstrings**: **English**.
- All **console output and user-facing messages**: **English**.
- No exceptions. _Why: English is the universal language of software development. Consistent language across all projects ensures cross-project readability and enables AI agents to work without language-switching overhead._

### 3.4 code example

Some proper code:

```python
def drytext_condense_file(input_path: str, output_path: str | None = None) -> str:
    """Condense a text file by removing redundancies.

yaml  
    Args:...

Returns:...  
    """
```


_THIS should be talic_

---

### 6.2 The weirdest shit

Install via pip:

```bash
# From the consuming project's activated .venv:
pip install -e path/to/tool
```

This creates a symlink so that source changes to `tool` are immediately visible to all projects without reinstalling.


Reference in `requirements.txt`:
```
tool @ file:///path/to/tool

```

### 8.2 things Idk

> [!CAUTION]
> another quote rendered as text.

Bye

## Items. *Nested* items.

Formatting **bold** *italic **both*** ~secondo alcuni questo è striked-out~, [link](https://www.google.it/?&hl=it)

* Item 1  
* Item 2

Or also

- Item 3
- Item 4

Or also

+ Item 3
+ Item 4

But ther's more

1. First item
2. Second item
3. Third item
    1. Indented item
    2. Indented item
4. Fourth item2. elenco 2  
   1. abc  
   2. cba  
   3. ddd  

Number-blind:

1. Item
1. Item
1. Item

---

- First item
- Second item
- Third item
    - Indented item
    - Indented item
- Fourth item

---

> #### The quarterly results look great!
>
> - Revenue was off the chart.
> - Profits were higher than ever.
>
>> *Everything* is going according to **plan**.

# Images

Trivial:

![](Foto.jpg)

Less trivial:

[![Trent and David](Foto.jpg "TR and DB")](https://en.wikipedia.org/wiki/I%27m_Afraid_of_Americans)

Even less trivial:
> - [![Trent and David](Foto.jpg "TR and DB")](https://en.wikipedia.org/wiki/I%27m_Afraid_of_Americans)

# What about reference style links?

 it was a [hobbit-hole][1], and that means comfort.

 > Same [link][2], different context. But what about just typing [![T&D](Foto.jpg)][2]?

 [1]: <https://en.wikipedia.org/wiki/Hobbit#Lifestyle> "Hobbit lifestyles"
 [2]: <https://en.wikipedia.org/wiki/I%27m_Afraid_of_Americans> "Other link"