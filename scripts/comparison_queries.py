"""Source-backed examples for the local comparison.

>>> len(QUERY_EXAMPLES)
36
"""

from dataclasses import dataclass
from typing import Literal

QueryKind = Literal["specific", "synonyms", "complex", "cross-source"]
KIND_NAMES = {
    "specific": "Specific",
    "synonyms": "Synonyms",
    "complex": "Complex",
    "cross-source": "Cross-source",
}

# Each source note names a passage or section that supports the expected publication.
# These are supported sources, not an exhaustive judgement of every relevant result.
SOURCES: dict[str, tuple[str, str, str]] = {
    "debt": (
        "data-story-schulden-in-der-stadt.md",
        "https://storymaps.arcgis.com/stories/1955ccada8d74ff6919e9e1397cb168a",
        "### Frönung",
    ),
    "silk": (
        "data-story-verbriefte-maerkte-seidene-beziehungen.md",
        "https://storymaps.arcgis.com/stories/90a309d6d21342608d0ad3ee16fb3f30",
        "### Briefe aus Bursa",
    ),
    "church": (
        "data-story-bleibt-die-kirche-in-der-stadt.md",
        "https://storymaps.arcgis.com/stories/34ef391bd4fa419cb82d488906608154",
        "## Hausbesitz",
    ),
    "tobacco": (
        "data-story-von-basler-fumoirs-und-schnupftabakdosen.md",
        "https://storymaps.arcgis.com/stories/e2096bc80f714932b8eba10ee7e23b4b",
        "## Tabak — Genussmittel für alle?",
    ),
    "koran": (
        "data-story-konzil-und-koran.md",
        "https://storymaps.arcgis.com/stories/0cac069fdac24f13a06377a1c7294a33",
        "Johannes von Ragusa",
    ),
    "bones": (
        "data-story-mit-bioarchaeologie-geschichte-schreiben.md",
        "https://storymaps.arcgis.com/stories/54d35e03bcdf4841b092d4c4906227e9",
        "## Sr- und O-Isotopenanalysen",
    ),
    "register": (
        "data-story-das-kontrollbuero-und-die-wundermaschine.md",
        "https://storymaps.arcgis.com/stories/6be823309a7b4254aa27b5486703b68b",
        "1969 begannen das Kontrollbüro",
    ),
    "iron": ("sgb-01.03-840481.md", "https://doi.org/10.21255/sgb-01.03-840481", "Basel-Gasfabrik"),
    "bishop": (
        "sgb-02.01-731545.md",
        "https://doi.org/10.21255/sgb-02.01-731545",
        "Verantwortlich für diese erste Stadtmauer ist Bischof Burkhard von Fenis",
    ),
    "quake": (
        "sgb-03.02-691441.md",
        "https://doi.org/10.21255/sgb-03.02-691441",
        "Auf Beben und Feuer folgte zuletzt eine Überschwemmung",
    ),
    "reformation": (
        "sgb-04.01-573018.md",
        "https://doi.org/10.21255/sgb-04.01-573018",
        "1529 in einem Bildersturm",
    ),
    "separation": (
        "sgb-05.05-622430.md",
        "https://doi.org/10.21255/sgb-05.05-622430",
        "Kantonstrennung von 1832/33",
    ),
    "rail": (
        "sgb-06.01-625359.md",
        "https://doi.org/10.21255/sgb-06.01-625359",
        "zwei Bahnhofsuhren",
    ),
    "war": ("sgb-07.01-137256.md", "https://doi.org/10.21255/sgb-07.01-137256", "Zwangstoleranz"),
    "environment": (
        "sgb-08.01-665666.md",
        "https://doi.org/10.21255/sgb-08.01-665666",
        "Schweizerhalle",
    ),
    "fish": (
        "sgb-09.03-874521.md",
        "https://doi.org/10.21255/sgb-09.03-874521",
        "Untergang der Berufsfischerei",
    ),
}


REFERENCE_KINDS: dict[str, QueryKind] = {
    SOURCES[key][1]: kind
    for key, kind in (
        ("fish", "synonyms"),
        ("debt", "complex"),
        ("silk", "specific"),
        ("church", "complex"),
        ("tobacco", "complex"),
        ("koran", "specific"),
        ("bones", "complex"),
        ("register", "complex"),
    )
}


@dataclass(frozen=True)
class QueryExample:
    """One query with known sources and local evidence notes.

    >>> QueryExample("q", "Topic", "specific", ("u",), (("a.md", "Text"),)).topic
    'Topic'
    """

    query: str
    topic: str
    kind: QueryKind
    expected_urls: tuple[str, ...]
    evidence: tuple[tuple[str, str], ...]


def example(topic: str, kind: QueryKind, query: str, *sources: str) -> QueryExample:
    """Attach canonical links and source notes to an example.

    >>> example("Debt", "specific", "Frönung", "debt").evidence[0][0]
    'data-story-schulden-in-der-stadt.md'
    """
    return QueryExample(
        query,
        topic,
        kind,
        tuple(SOURCES[key][1] for key in sources),
        tuple((SOURCES[key][0], SOURCES[key][2]) for key in sources),
    )


QUERY_EXAMPLES = (
    example(
        "Schulden",
        "specific",
        "Frönung und Vergicht: Wie trieb das Basler Stadtgericht im 15. Jahrhundert Schulden ein?",
        "debt",
    ),
    example(
        "Schulden",
        "synonyms",
        "Welche Möglichkeiten hatten Geldgeber im spätmittelalterlichen Basel, ausstehende Zahlungen gerichtlich einzufordern?",
        "debt",
    ),
    example(
        "Seidenhandel",
        "specific",
        "Emanuel Falkeisen, Bursa und Forcart-Weiss: Rohseidenhandel in den 1830er- und 1840er-Jahren",
        "silk",
    ),
    example(
        "Seidenhandel",
        "complex",
        "Wie halfen Kaufleute, Banken und Geschäftsbriefe den Basler Bandfabrikanten, Rohmaterial aus dem Osmanischen Reich zu beziehen?",
        "silk",
    ),
    example(
        "Kirchlicher Hausbesitz",
        "specific",
        "Erbleihe, Ehrschatz und Grundzins bei Basler Häusern",
        "church",
    ),
    example(
        "Kirchlicher Hausbesitz",
        "synonyms",
        "Weshalb mussten Hauseigentümer in Basel Geld an geistliche Institutionen zahlen, obwohl sie ihre Liegenschaften verkaufen konnten?",
        "church",
    ),
    example(
        "Tabak",
        "specific",
        "Tabak im Dreissigjährigen Krieg: Soldaten, Matrosen und Basler Rauchkultur",
        "tobacco",
    ),
    example(
        "Tabak",
        "complex",
        "Warum verbreitete sich das Rauchen gleichzeitig unter Wohlhabenden und einfachen Leuten, und weshalb blieb Tabak als Arznei akzeptiert?",
        "tobacco",
    ),
    example(
        "Koran und Konzil",
        "specific",
        "Johannes von Ragusa, arabische Koranhandschrift und Basel 1435",
        "koran",
    ),
    example(
        "Koran und Konzil",
        "synonyms",
        "Wie gelangte während der grossen Kirchenversammlung eine Handschrift der heiligen Schrift des Islam nach Basel?",
        "koran",
    ),
    example(
        "Bioarchäologie",
        "specific",
        "Basel-Waisenhaus: Strontium-, Sauerstoff-, Kohlenstoff- und Stickstoffisotope",
        "bones",
    ),
    example(
        "Bioarchäologie",
        "complex",
        "Wie lassen sich Herkunft und Ernährung spätantiker Bestatteter unterscheiden, wenn man Zähne und Knochen naturwissenschaftlich untersucht?",
        "bones",
    ),
    example(
        "Einwohnerregister",
        "specific",
        "Kontrollbüro und ZED: Digitalisierung des Einwohnerregisters ab 1969",
        "register",
    ),
    example(
        "Einwohnerregister",
        "synonyms",
        "Wie begann die Basler Verwaltung Ende der 1960er-Jahre, Angaben zur Wohnbevölkerung elektronisch zu speichern?",
        "register",
    ),
    example(
        "Eisenzeit",
        "specific",
        "Basel-Gasfabrik und Münsterhügel: Siedlungen der späten Latènezeit",
        "iron",
    ),
    example(
        "Eisenzeit",
        "synonyms",
        "Wie unterschieden sich die offene Siedlung am Rhein und der befestigte Wohnplatz auf dem Hügel in der späten Eisenzeit?",
        "iron",
    ),
    example(
        "Bischof und Stadtmauer",
        "specific",
        "Burkhard von Fenis und die erste Basler Stadtmauer um 1080",
        "bishop",
    ),
    example(
        "Bischof und Stadtmauer",
        "synonyms",
        "Welche Rolle spielte der geistliche Stadtherr bei der Befestigung Basels im späten 11. Jahrhundert?",
        "bishop",
    ),
    example(
        "Erdbeben",
        "specific",
        "18. Oktober 1356: Erdbeben, Stadtbrand und aufgestauter Birsig",
        "quake",
    ),
    example(
        "Erdbeben",
        "complex",
        "Wie konnte ein Erdstoss im mittelalterlichen Basel zunächst Feuer und danach eine Überschwemmung auslösen?",
        "quake",
    ),
    example(
        "Reformation",
        "specific",
        "Basel 1529: Bildersturm und Einführung der Reformation",
        "reformation",
    ),
    example(
        "Reformation",
        "synonyms",
        "Wie setzte sich in Basel der neue evangelische Glaube gegen die bisherige kirchliche Ordnung durch?",
        "reformation",
    ),
    example(
        "Kantonstrennung",
        "specific",
        "Kantonstrennung 1832/33: Stephan Gutzwiller und der Konflikt zwischen Stadt und Landschaft",
        "separation",
    ),
    example(
        "Kantonstrennung",
        "complex",
        "Wie führten Streitfragen über politische Mitsprache und eine neue Verfassung zum bewaffneten Bruch zwischen Basel und seinem Umland?",
        "separation",
    ),
    example(
        "Eisenbahn und Zeit",
        "specific",
        "Basler Centralbahnhof: Berner Zeit, Pariser Zeit und zwei Bahnhofsuhren",
        "rail",
    ),
    example(
        "Eisenbahn und Zeit",
        "complex",
        "Warum mussten Bahnreisende in Basel im 19. Jahrhundert unterschiedliche Uhrzeiten beachten, und wie löste man dieses Problem?",
        "rail",
    ),
    example(
        "Aufenthaltsrecht im Krieg",
        "specific",
        "Basel 1914: Refrektäre, Niederlassungsbewilligung und Zwangstoleranz",
        "war",
    ),
    example(
        "Aufenthaltsrecht im Krieg",
        "complex",
        "Warum verloren Männer aus den Nachbarländern während des Ersten Weltkriegs ihr Aufenthaltsrecht, wenn sie nicht zum Militär einrückten?",
        "war",
    ),
    example(
        "Schweizerhalle",
        "specific",
        "Schweizerhalle 1986: Sandoz-Brand, Fischsterben und Proteste in Basel",
        "environment",
    ),
    example(
        "Schweizerhalle",
        "complex",
        "Wie wurde ein Lagerhallenbrand zur grenzüberschreitenden Gewässerkatastrophe, und warum erschütterte er das Vertrauen in Behörden und Chemieindustrie?",
        "environment",
    ),
    example(
        "Rheinfischerei",
        "specific",
        "Rheinfischerei: Lachsfang und Ende der Basler Berufsfischerei in den 1950er-Jahren",
        "fish",
    ),
    example(
        "Rheinfischerei",
        "synonyms",
        "Weshalb konnten Basler Fischer vom Fang der flussaufwärts ziehenden Lachse immer weniger leben?",
        "fish",
    ),
    # The railway chapter covers policing arrivals as well as trade and timetables.
    example(
        "Zuzug und Kontrolle",
        "cross-source",
        "Wie veränderten sich die Möglichkeiten der Basler Behörden, Zuzug zu kontrollieren, vom Bahnhof des 19. Jahrhunderts bis zum computerisierten Einwohnerregister?",
        "rail",
        "register",
    ),
    # The chapter explains the religious change. The story traces property claims afterwards.
    example(
        "Reformation und Eigentum",
        "cross-source",
        "Wie veränderte die Reformation die kirchliche Macht in Basel, und welche Ansprüche auf Häuser blieben danach bestehen?",
        "reformation",
        "church",
    ),
    # The story covers the silk network. The railway chapter covers growing global trade.
    example(
        "Internationale Warenströme",
        "cross-source",
        "Wie verbanden der Rohseidenhandel mit dem Osmanischen Reich und der Ausbau der Eisenbahn Basel mit internationalen Warenströmen?",
        "silk",
        "rail",
    ),
    # The two chapters cover long-term habitat changes and the 1986 disaster respectively.
    example(
        "Rhein und Umweltschutz",
        "cross-source",
        "Wie veränderten Eingriffe in den Rhein die Fischerei, und wie prägte die Chemiekatastrophe von 1986 den Basler Umweltschutz?",
        "fish",
        "environment",
    ),
)
