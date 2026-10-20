"""The published sources behind every number and sentence of the guidance.

Each constant in app.guidance carries a comment naming its SourceId. A response
lists only the sources it cites (cited_sources), so a reader can check each claim.
A source is listed for what it was checked to say; where a rule goes further than
its source (a Formiq product rule), the comment next to the rule says so.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class SourceId(StrEnum):
    ISSN_PROTEIN_2017 = "ISSN_PROTEIN_2017"
    ISSN_TIMING_2017 = "ISSN_TIMING_2017"
    MORTON_2018 = "MORTON_2018"
    SCHOENFELD_ARAGON_2018 = "SCHOENFELD_ARAGON_2018"
    ACSM_NUTRITION_2016 = "ACSM_NUTRITION_2016"
    ACSM_FLUID_2007 = "ACSM_FLUID_2007"
    COMPENDIUM_2024 = "COMPENDIUM_2024"
    ACSM_POSITION_2011 = "ACSM_POSITION_2011"
    CHEUNG_DOMS_2003 = "CHEUNG_DOMS_2003"
    AASM_SLEEP_2015 = "AASM_SLEEP_2015"
    USDA_FDC = "USDA_FDC"
    FDA_ALLERGENS = "FDA_ALLERGENS"
    CDC_RHABDO = "CDC_RHABDO"


@dataclass(frozen=True)
class Source:
    id: SourceId
    citation: str
    url: str


@dataclass(frozen=True)
class GuidanceItem:
    """One piece of general guidance, and the sources it rests on. It holds no
    number computed from a user's data: those are estimates (app.guidance.nutrition)."""

    code: str
    text: str
    source_ids: tuple[SourceId, ...] = ()


# In the order the sources are listed in a response.
SOURCES: tuple[Source, ...] = (
    Source(
        SourceId.ISSN_PROTEIN_2017,
        "Jäger R, Kerksick CM, Campbell BI, et al. International Society of Sports Nutrition "
        "Position Stand: protein and exercise. J Int Soc Sports Nutr. 2017;14:20.",
        "https://doi.org/10.1186/s12970-017-0177-8",
    ),
    Source(
        SourceId.ISSN_TIMING_2017,
        "Kerksick CM, Arent S, Schoenfeld BJ, et al. International Society of Sports Nutrition "
        "position stand: nutrient timing. J Int Soc Sports Nutr. 2017;14:33.",
        "https://doi.org/10.1186/s12970-017-0189-4",
    ),
    Source(
        SourceId.MORTON_2018,
        "Morton RW, Murphy KT, McKellar SR, et al. A systematic review, meta-analysis and "
        "meta-regression of the effect of protein supplementation on resistance "
        "training-induced gains in muscle mass and strength in healthy adults. "
        "Br J Sports Med. 2018;52(6):376-384.",
        "https://doi.org/10.1136/bjsports-2017-097608",
    ),
    Source(
        SourceId.SCHOENFELD_ARAGON_2018,
        "Schoenfeld BJ, Aragon AA. How much protein can the body use in a single meal for "
        "muscle-building? Implications for daily protein distribution. "
        "J Int Soc Sports Nutr. 2018;15:10.",
        "https://doi.org/10.1186/s12970-018-0215-1",
    ),
    Source(
        SourceId.ACSM_NUTRITION_2016,
        "Thomas DT, Erdman KA, Burke LM. Nutrition and Athletic Performance: joint position "
        "of the Academy of Nutrition and Dietetics, Dietitians of Canada and the American "
        "College of Sports Medicine. Med Sci Sports Exerc. 2016;48(3):543-568 (published "
        "concurrently in J Acad Nutr Diet. 2016;116(3):501-528).",
        "https://doi.org/10.1249/MSS.0000000000000852",
    ),
    Source(
        SourceId.ACSM_FLUID_2007,
        "Sawka MN, Burke LM, Eichner ER, Maughan RJ, Montain SJ, Stachenfeld NS. American "
        "College of Sports Medicine position stand. Exercise and fluid replacement. "
        "Med Sci Sports Exerc. 2007;39(2):377-390.",
        "https://doi.org/10.1249/mss.0b013e31802ca597",
    ),
    Source(
        SourceId.COMPENDIUM_2024,
        "Herrmann SD, Willis EA, Ainsworth BE, et al. 2024 Adult Compendium of Physical "
        "Activities: a third update of the energy costs of human activities. "
        "J Sport Health Sci. 2024;13(1):6-12. Codes 02050 and 02054, pacompendium.com.",
        "https://pacompendium.com/conditioning-exercise/",
    ),
    Source(
        SourceId.ACSM_POSITION_2011,
        "Garber CE, Blissmer B, Deschenes MR, et al. American College of Sports Medicine "
        "position stand. Quantity and quality of exercise for developing and maintaining "
        "cardiorespiratory, musculoskeletal, and neuromotor fitness in apparently healthy "
        "adults. Med Sci Sports Exerc. 2011;43(7):1334-1359.",
        "https://doi.org/10.1249/mss.0b013e318213fefb",
    ),
    Source(
        SourceId.CHEUNG_DOMS_2003,
        "Cheung K, Hume P, Maxwell L. Delayed onset muscle soreness: treatment strategies "
        "and performance factors. Sports Med. 2003;33(2):145-164.",
        "https://doi.org/10.2165/00007256-200333020-00005",
    ),
    Source(
        SourceId.AASM_SLEEP_2015,
        "Watson NF, Badr MS, Belenky G, et al. Recommended amount of sleep for a healthy "
        "adult: a joint consensus statement of the American Academy of Sleep Medicine and "
        "Sleep Research Society. Sleep. 2015;38(6):843-844.",
        "https://doi.org/10.5665/sleep.4716",
    ),
    Source(
        SourceId.USDA_FDC,
        "U.S. Department of Agriculture, Agricultural Research Service. FoodData Central "
        "(SR Legacy foods).",
        "https://fdc.nal.usda.gov/",
    ),
    Source(
        SourceId.FDA_ALLERGENS,
        "U.S. Food and Drug Administration. Food Allergies: the nine major food allergens "
        "(Food Allergen Labeling and Consumer Protection Act of 2004, as extended by the "
        "FASTER Act).",
        "https://www.fda.gov/food/nutrition-food-labeling-and-critical-foods/food-allergies",
    ),
    Source(
        SourceId.CDC_RHABDO,
        "Centers for Disease Control and Prevention, NIOSH. Rhabdomyolysis and Work.",
        "https://www.cdc.gov/niosh/rhabdo/about/index.html",
    ),
)


def cited_sources(ids: Iterable[SourceId | str]) -> tuple[Source, ...]:
    """The registered sources among ids, once each, in registry order. An id that
    is not registered is a bug, so it raises rather than being left out."""
    cited = {SourceId(source_id) for source_id in ids}
    return tuple(source for source in SOURCES if source.id in cited)
