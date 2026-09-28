from html.parser import HTMLParser


class _DescriptionText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "ul", "ol"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li", "h1", "h2", "h3", "ul", "ol"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    parser = _DescriptionText()
    parser.feed(value)
    return (
        "\n".join(
            line
            for raw in "".join(parser.parts).splitlines()
            if (line := " ".join(raw.split()))
        )
        or None
    )
