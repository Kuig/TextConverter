from __future__ import annotations
import os
import sys
import textconverter

os.makedirs("DocsOutput", exist_ok=True)

def run_discard_test():
    import shutil
    # Clean up any existing folder first
    if os.path.exists("DocsOutput/Pane_discard_images"):
        shutil.rmtree("DocsOutput/Pane_discard_images")
    textconverter.save_to_file(
        "https://daginoilbonaparte.it/blog-di-cucina/ricetta-pane-impasta/",
        "DocsOutput/Pane_discard.md",
        image_handling="discard",
        code_parsing=True,
        extract_html=True
    )
    if os.path.exists("DocsOutput/Pane_discard_images"):
        raise RuntimeError("Image folder was created even though image_handling is set to 'discard'!")

def run_caption_test():
    html_content = """
    <div class="thumbcaption">
        Una serie di <a href="http://example.com/codon">codoni</a> su una molecola di <a href="http://example.com/rna">RNA messaggero</a>.
    </div>
    """
    result = textconverter.convert(html_content, to_format="markdown", from_format="html")
    expected = "Una serie di [codoni](http://example.com/codon) su una molecola di [RNA messaggero](http://example.com/rna)."
    if expected not in result:
         raise RuntimeError(f"Caption was not wrapped correctly! Got: {repr(result)}")

tests = [
    (
        "Bread test",
        lambda: textconverter.save_to_file(
            "https://daginoilbonaparte.it/blog-di-cucina/ricetta-pane-impasta/",
            "DocsOutput/Pane.md",
            image_handling="link",
            code_parsing=True,
            extract_html=True,
            template="dark-theme"
        )
    ),
    (
        "Bread test with discard image handling",
        run_discard_test
    ),
    (
        "Wikipedia caption paragraph wrapping",
        run_caption_test
    )
    #(
    #    "Tesi with unfenced code",
    #    lambda: textconverter.save_to_file(
    #        "DocsInput/Tesi.pdf",
    #        "DocsOutput/Tesi.html",
    #        image_handling="link",
    #        code_parsing=True,
    #        template="dark-theme"
    #    )
    #),
    #(
    #    "Markdown CodeTest with blank lines",
    #    lambda: textconverter.save_to_file(
    #        "DocsInput/CodeTest.md",
    #        "DocsOutput/CodeTest.html",
    #        image_handling="link",
    #        code_parsing=True,
    #        template="dark-theme"
    #    )
    #) 
    # (
    #     "MD to MD",
    #     lambda: core.save_to_file(
    #         "D:/Progetti/IA/TextConverter/DocsInput/SampleMD.md",
    #         "DocsOutput/SampleMD.md",
    #         image_handling="discard",
    #         code_parsing=False
    #     )
    # ),
    # (
    #     "MD to HTML",
    #     lambda: core.save_to_file(
    #         "D:/Progetti/IA/TextConverter/DocsInput/SampleMD.md",
    #         "DocsOutput/SampleMD.html",
    #         image_handling="discard",
    #         code_parsing=False,
    #         template="light-theme"
    #     )
    # )
    # (
    #     "Wikipedia Swish Function",
    #     lambda: core.save_to_file(
    #         "https://en.wikipedia.org/wiki/Swish_function",
    #         "DocsOutput/Swish.html",
    #         image_handling="discard",
    #         code_parsing=True,
    #         extract_html=True,
    #         template="light-theme"
    #     )
    # )
    # (
    #     "SMC Network",
    #     lambda: core.save_to_file(
    #         "https://smcnetwork.org/index.html",
    #         "DocsOutput/SMCNetwork.html",
    #         image_handling="link",
    #         code_parsing=True,
    #         extract_html=True,
    #         template="light-theme"
    #     )
    # ),
    # (
    #     "Signal Perspective (FFmpeg)",
    #     lambda: core.save_to_file(
    #         "https://www.signalperspective.com/how-to-with-ffmpeg/",
    #         "DocsOutput/HowToFfmpeg.html",
    #         image_handling="link",
    #         code_parsing=True,
    #         extract_html=True,
    #         template="light-theme"
    #     )
    # ),
    # (
    #     "CCRMA Stanford",
    #     lambda: core.save_to_file(
    #         "https://ccrma.stanford.edu/",
    #         "DocsOutput/Ccrrma.html",
    #         image_handling="link",
    #         code_parsing=True,
    #         extract_html=True,
    #         template="light-theme"
    #     )
    # ),
    # (
    #     "CCRMA Stanford Research",
    #     lambda: core.save_to_file(
    #         "https://ccrma.stanford.edu/~jos/pasp/Delay_Lines.html",
    #         "DocsOutput/Ccrrma_research.html",
    #         image_handling="discard",
    #         code_parsing=True,
    #         extract_html=True,
    #         template="light-theme"
    #     )
    # ),
    # (
    #     "Unimi Presti Homepage",
    #     lambda: core.save_to_file(
    #         "https://homes.di.unimi.it/presti/index.php?p=3&l=1",
    #         "DocsOutput/Presti.html",
    #         image_handling="link",
    #         code_parsing=True,
    #         extract_html=True,
    #         template="light-theme"
    #     )
    # )

]

failed_tests = []

for name, test_func in tests:
    print(f"\n--- Testing: {name} ---")
    try:
        test_func()
        print(f"✅ {name} conversion succeeded!")
    except Exception as exc:
        print(f"❌ {name} conversion failed: {exc}", file=sys.stderr)
        failed_tests.append((name, str(exc)))

print("\n" + "=" * 40)
print("             TEST SUMMARY")
print("=" * 40)
if failed_tests:
    print(f"❌ Failed {len(failed_tests)} out of {len(tests)} tests:\n")
    for name, err in failed_tests:
        print(f"- {name}: {err}")
    print("=" * 40)
    sys.exit(1)
else:
    print("✅ All tests passed successfully!")
    print("=" * 40)
    sys.exit(0)