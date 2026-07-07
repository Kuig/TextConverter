# Test conversione codice

Questo è un file di test per verificare la corretta elaborazione e renderizzazione dei blocchi di codice da parte del parser markdown.

Di seguito è riportato un semplice algoritmo in Python:

```python
def fibonacci(n):
    """Calcola l'n-esimo numero della serie di Fibonacci."""
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    else:
        return fibonacci(n-1) + fibonacci(n-2)

print("Risultato:", fibonacci(10))
```

# Unfenced

E questo è un esempio di codice in linea: usa la funzione `print()` per stampare il risultato a schermo. Speriamo che venga formattato correttamente sia in HTML che in LaTeX!

Ora un esempio di codice "unfenced":

def fibonacci(n):
    """Calcola l'n-esimo numero della serie di Fibonacci."""
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    else:
        return fibonacci(n-1) + fibonacci(n-2)

print("Risultato:", fibonacci(10))

# More on `code`

If the word or phrase you want to denote as code includes one or more backticks, you can escape it by enclosing the word or phrase in double backticks (``).

``Use `code` in your Markdown file.``