from __future__ import annotations

from datetime import UTC, datetime

from notibot.sources.reduno import RedunoSource
from notibot.sources.unitel import UnitelSource

UNITEL_LISTING = """
<div class="texts">
  <div class="data">
    <a href="/noticias/seguridad/policia-detiene-a-sospechoso-OB24439250">
      <h3 class="title">Policía detiene a sospechoso</h3>
    </a>
  </div>
  <div class="properties">
    <div class="section"><a href="/noticias/seguridad">Seguridad</a></div>
    <span class="publicationDate">Hace 2 horas</span>
  </div>
  <h4 class="lead">Un operativo en La Paz terminó con una aprehensión.</h4>
  <img src="/img/foto.jpg" />
</div>
"""

REDUNO_LISTING = """
<article>
  <a href="/noticias/policia-detiene-a-sospechoso-20261028202249">
    <h2>Policía detiene a sospechoso</h2>
    <img src="/img/foto.jpg" />
  </a>
</article>
"""

ARTICLE_JSONLD = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "headline": "Titular real del artículo",
  "datePublished": "2026-10-28T18:20:00",
  "articleBody": "&lt;p&gt;Cuerpo &amp; detalles&lt;/p&gt;",
  "description": "Descripción real",
  "image": {"url": "https://cdn.example.com/foto.jpg"},
  "articleSection": "Seguridad"
}
</script>
</head><body></body></html>
"""


def test_unitel_listing_parser() -> None:
    source = UnitelSource()
    try:
        items = source.parse_listing(UNITEL_LISTING, "https://unitel.bo/noticias")
    finally:
        source.close()

    assert len(items) == 1
    item = items[0]
    assert item.title == "Policía detiene a sospechoso"
    assert item.code == "OB24439250"
    assert item.section == "Seguridad"
    assert item.published_at is not None
    assert item.date_estimated is True


def test_reduno_listing_parser_uses_url_timestamp() -> None:
    source = RedunoSource()
    try:
        items = source.parse_listing(
            REDUNO_LISTING, "https://www.reduno.com.bo/noticias"
        )
    finally:
        source.close()

    assert len(items) == 1
    item = items[0]
    assert item.code == "20261028202249"
    assert item.published_at == datetime(
        2026, 10, 29, 0, 22, 49, tzinfo=UTC
    )
    assert item.date_estimated is True


def test_parse_article_jsonld() -> None:
    source = UnitelSource()
    try:
        data = source.parse_article(
            ARTICLE_JSONLD,
            "https://unitel.bo/noticias/seguridad/foo-OB24439250",
        )
    finally:
        source.close()

    assert data.title == "Titular real del artículo"
    assert data.published_at == datetime(
        2026, 10, 28, 18, 20, tzinfo=UTC
    )
    assert data.body == "Cuerpo & detalles"
    assert data.description == "Descripción real"
    assert data.section == "Seguridad"
    assert data.image == "https://cdn.example.com/foto.jpg"


def test_parse_article_graph_and_meta_fallback() -> None:
    html = """
    <html><head>
      <meta property="article:published_time" content="2026-10-28T10:00:00-04:00">
      <meta property="og:title" content="Titular desde meta">
      <meta property="og:description" content="Descripción desde meta">
      <script type="application/ld+json">
      {"@context": "https://schema.org", "@graph": [
        {"@type": "WebSite", "name": "Unitel"},
        {"@type": "NewsArticle", "headline": "Titular desde graph",
         "datePublished": "2026-10-28T14:00:00Z"}
      ]}
      </script>
    </head><body><p>Un párrafo suficientemente largo para ser considerado cuerpo de la noticia y no ser descartado por el filtro de longitud.</p></body></html>
    """
    source = UnitelSource()
    try:
        data = source.parse_article(html, "https://unitel.bo/noticias/foo-OB24439250")
    finally:
        source.close()

    assert data.title == "Titular desde graph"
    assert data.published_at == datetime(
        2026, 10, 28, 14, 0, tzinfo=UTC
    )
    assert data.body
