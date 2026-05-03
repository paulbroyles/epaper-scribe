"""Roman Catholic General Calendar — pure-Python implementation.

Covers the universal General Roman Calendar (GRC). Regional variations are
not included. Moveable feasts are computed from Easter using the anonymous
Gregorian algorithm. Fixed feasts follow the 1969 GRC as currently in force.

Rank values (from highest to lowest):
  SOLEMNITY > FEAST > MEMORIAL > OPT_MEMORIAL

When a lower-ranked fixed feast falls on the same day as a higher-ranked
moveable feast, the moveable feast takes precedence and the fixed feast is
suppressed. Sundays in Ordinary Time suppress optional memorials.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class CatholicFeast:
    name: str
    rank: str  # "SOLEMNITY" | "FEAST" | "MEMORIAL" | "OPT_MEMORIAL"

    @property
    def rank_value(self) -> int:
        return {"SOLEMNITY": 4, "FEAST": 3, "MEMORIAL": 2, "OPT_MEMORIAL": 1}.get(
            self.rank, 0
        )


# ---------------------------------------------------------------------------
# Easter calculation (anonymous Gregorian algorithm)
# ---------------------------------------------------------------------------

def easter_date(year: int) -> date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month, day = divmod(h + ll - 7 * m + 114, 31)
    return date(year, month, day + 1)


# ---------------------------------------------------------------------------
# Fixed feasts  (month, day) → list[CatholicFeast]
# ---------------------------------------------------------------------------

_S = "SOLEMNITY"
_F = "FEAST"
_M = "MEMORIAL"
_O = "OPT_MEMORIAL"

FIXED: dict[tuple[int, int], list[CatholicFeast]] = {
    # January
    (1, 1):  [CatholicFeast("Mary, Mother of God", _S)],
    (1, 2):  [CatholicFeast("Saints Basil the Great and Gregory Nazianzen, Bishops and Doctors", _M)],
    (1, 3):  [CatholicFeast("The Most Holy Name of Jesus", _O)],
    (1, 7):  [CatholicFeast("Saint Raymond of Penyafort, Priest", _O)],
    (1, 13): [CatholicFeast("Saint Hilary of Poitiers, Bishop and Doctor", _O)],
    (1, 17): [CatholicFeast("Saint Anthony of Egypt, Abbot", _M)],
    (1, 20): [CatholicFeast("Saints Fabian, Pope, and Sebastian, Martyrs", _O)],
    (1, 21): [CatholicFeast("Saint Agnes, Virgin and Martyr", _M)],
    (1, 22): [CatholicFeast("Saint Vincent, Deacon and Martyr", _O)],
    (1, 24): [CatholicFeast("Saint Francis de Sales, Bishop and Doctor", _M)],
    (1, 25): [CatholicFeast("Conversion of Saint Paul, Apostle", _F)],
    (1, 26): [CatholicFeast("Saints Timothy and Titus, Bishops", _M)],
    (1, 27): [CatholicFeast("Saint Angela Merici, Virgin", _O)],
    (1, 28): [CatholicFeast("Saint Thomas Aquinas, Priest and Doctor", _M)],
    (1, 31): [CatholicFeast("Saint John Bosco, Priest", _M)],
    # February
    (2, 2):  [CatholicFeast("Presentation of the Lord", _F)],
    (2, 3):  [CatholicFeast("Saint Blase, Bishop Martyr and Saint Ansgar, Bishop", _O)],
    (2, 5):  [CatholicFeast("Saint Agatha, Virgin and Martyr", _M)],
    (2, 6):  [CatholicFeast("Saint Paul Miki and Companions, Martyrs", _M)],
    (2, 8):  [CatholicFeast("Saint Jerome Emiliani and Saint Josephine Bakhita, Virgin", _O)],
    (2, 10): [CatholicFeast("Saint Scholastica, Virgin", _M)],
    (2, 11): [CatholicFeast("Our Lady of Lourdes", _O)],
    (2, 14): [CatholicFeast("Saints Cyril, Monk and Methodius, Bishop", _M)],
    (2, 17): [CatholicFeast("Seven Holy Founders of the Servite Order", _O)],
    (2, 21): [CatholicFeast("Saint Peter Damian, Bishop and Doctor of the Church", _O)],
    (2, 22): [CatholicFeast("Chair of Saint Peter, Apostle", _F)],
    (2, 23): [CatholicFeast("Saint Polycarp, Bishop and Martyr", _M)],
    # March
    (3, 4):  [CatholicFeast("Saint Casimir", _O)],
    (3, 7):  [CatholicFeast("Saints Perpetua and Felicity, Martyrs", _M)],
    (3, 8):  [CatholicFeast("Saint John of God, Religious", _O)],
    (3, 9):  [CatholicFeast("Saint Frances of Rome, Religious", _O)],
    (3, 17): [CatholicFeast("Saint Patrick, Bishop", _O)],
    (3, 18): [CatholicFeast("Saint Cyril of Jerusalem, Bishop and Doctor", _O)],
    (3, 19): [CatholicFeast("Joseph, Husband of Mary", _S)],
    (3, 23): [CatholicFeast("Saint Turibius of Mogrovejo, Bishop", _O)],
    (3, 25): [CatholicFeast("Annunciation", _S)],
    # April
    (4, 2):  [CatholicFeast("Saint Francis of Paola, Hermit", _O)],
    (4, 4):  [CatholicFeast("Saint Isidore of Seville, Bishop and Doctor of the Church", _O)],
    (4, 5):  [CatholicFeast("Saint Vincent Ferrer, Priest", _O)],
    (4, 7):  [CatholicFeast("Saint John Baptist de la Salle, Priest", _M)],
    (4, 11): [CatholicFeast("Saint Stanislaus, Bishop and Martyr", _M)],
    (4, 13): [CatholicFeast("Saint Martin I, Pope and Martyr", _O)],
    (4, 21): [CatholicFeast("Saint Anselm of Canterbury, Bishop and Doctor of the Church", _O)],
    (4, 23): [CatholicFeast("Saint George, Martyr/Saint Adalbert, Bishop and Martyr", _O)],
    (4, 24): [CatholicFeast("Saint Fidelis of Sigmaringen, Priest and Martyr", _O)],
    (4, 25): [CatholicFeast("Saint Mark the Evangelist", _F)],
    (4, 28): [CatholicFeast("Saint Peter Chanel, Priest and Martyr/Saint Louis Grignon de Montfort, Priest", _O)],
    (4, 29): [CatholicFeast("Saint Catherine of Siena, Virgin and Doctor of The Church, Patron of Europe", _M)],
    (4, 30): [CatholicFeast("Saint Pius V, Pope", _O)],
    # May
    (5, 1):  [CatholicFeast("Saint Joseph the Worker", _O)],
    (5, 2):  [CatholicFeast("Saint Athanasius, Bishop and Doctor", _M)],
    (5, 3):  [CatholicFeast("Saints Philip and James, Apostles", _F)],
    (5, 12): [CatholicFeast("Saints Nereus and Achilleus, Martyrs/Saint Pancras, Martyr", _O)],
    (5, 13): [CatholicFeast("Our Lady of Fatima", _O)],
    (5, 14): [CatholicFeast("Saint Matthias the Apostle", _F)],
    (5, 18): [CatholicFeast("Saint John I, Pope and Martyr", _O)],
    (5, 20): [CatholicFeast("Saint Bernardine of Siena, Priest", _O)],
    (5, 21): [CatholicFeast("Saint Christopher Magallanes and Companions, Martyrs", _O)],
    (5, 22): [CatholicFeast("Saint Rita of Cascia", _O)],
    (5, 25): [CatholicFeast("Saint Bede the Venerable, Priest and Doctor/Saint Gregory VII, Pope/Saint Mary Magdalene de Pazzi, Virgin", _O)],
    (5, 26): [CatholicFeast("Saint Philip Neri, Priest", _M)],
    (5, 27): [CatholicFeast("Saint Augustine of Canterbury, Bishop", _O)],
    (5, 31): [CatholicFeast("Visitation of the Blessed Virgin Mary", _F)],
    # June
    (6, 1):  [CatholicFeast("Saint Justin, Martyr", _M)],
    (6, 2):  [CatholicFeast("Saints Marcellinus and Peter, Martyrs", _O)],
    (6, 3):  [CatholicFeast("Saint Charles Lwanga and Companions, Martyrs", _M)],
    (6, 5):  [CatholicFeast("Saint Boniface, Bishop and Martyr", _M)],
    (6, 6):  [CatholicFeast("Saint Norbert, Bishop", _O)],
    (6, 9):  [CatholicFeast("Saint Ephrem, Deacon and Doctor", _O)],
    (6, 11): [CatholicFeast("Saint Barnabas the Apostle", _M)],
    (6, 13): [CatholicFeast("Saint Anthony of Padua, Priest and Doctor", _M)],
    (6, 19): [CatholicFeast("Saint Romuald, Abbot", _O)],
    (6, 21): [CatholicFeast("Saint Aloysius Gonzaga, Religious", _M)],
    (6, 22): [CatholicFeast("Saint Paulinus of Nola, Bishop/Saints John Fisher, Bishop and Thomas More, Martyrs", _O)],
    (6, 24): [CatholicFeast("Birth of Saint John the Baptist", _S)],
    (6, 27): [CatholicFeast("Saint Cyril of Alexandria, Bishop and Doctor", _O)],
    (6, 28): [CatholicFeast("Saint Irenaeus, Bishop and Martyr", _M)],
    (6, 29): [CatholicFeast("Saints Peter and Paul, Apostles", _S)],
    (6, 30): [CatholicFeast("First Martyrs of the Church of Rome", _O)],
    # July
    (7, 3):  [CatholicFeast("Saint Thomas, Apostle", _F)],
    (7, 4):  [CatholicFeast("Saint Elizabeth of Portugal", _O)],
    (7, 5):  [CatholicFeast("Saint Anthony Mary Zaccaria, Priest", _O)],
    (7, 6):  [CatholicFeast("Saint Maria Goretti, Virgin and Martyr", _O)],
    (7, 9):  [CatholicFeast("Saint Augustine Zhao Rong and Companions, Martyrs", _O)],
    (7, 11): [CatholicFeast("Saint Benedict of Nursia, Abbot, Patron of Europe", _M)],
    (7, 13): [CatholicFeast("Saint Henry, Bishop and Martyr", _O)],
    (7, 14): [CatholicFeast("Saint Camillus de Lellis, Priest", _O)],
    (7, 15): [CatholicFeast("Saint Bonaventure, Bishop and Doctor", _M)],
    (7, 16): [CatholicFeast("Our Lady of Mount Carmel", _O)],
    (7, 20): [CatholicFeast("Saint Apollinaris", _O)],
    (7, 21): [CatholicFeast("Saint Lawrence of Brindisi, Priest and Doctor", _O)],
    (7, 22): [CatholicFeast("Saint Mary Magdalene", _F)],
    (7, 23): [CatholicFeast("Saint Bridget of Sweden, Religious, Patron of Europe", _O)],
    (7, 24): [CatholicFeast("Saint Charbel Makhlouf, Priest and Hermit", _O)],
    (7, 25): [CatholicFeast("Saint James, Apostle", _F)],
    (7, 26): [CatholicFeast("Saints Joachim and Anne", _M)],
    (7, 29): [CatholicFeast("Saint Martha", _M)],
    (7, 30): [CatholicFeast("Saint Peter Chrysologus, Bishop and Doctor", _O)],
    (7, 31): [CatholicFeast("Saint Ignatius of Loyola, Priest", _M)],
    # August
    (8, 1):  [CatholicFeast("Saint Alphonsus Maria de Liguori, Bishop and Doctor of the Church", _M)],
    (8, 2):  [CatholicFeast("Saint Eusebius of Vercelli, Bishop/Saint Peter Julian Eymard, Priest", _O)],
    (8, 4):  [CatholicFeast("Saint Jean Vianney (the Cure of Ars), Priest", _M)],
    (8, 5):  [CatholicFeast("Dedication of the Basilica of Saint Mary Major", _O)],
    (8, 6):  [CatholicFeast("Transfiguration", _F)],
    (8, 7):  [CatholicFeast("Saint Sixtus II, Pope, and Companions, Martyrs/Saint Cajetan, Priest", _O)],
    (8, 8):  [CatholicFeast("Saint Dominic, Priest", _M)],
    (8, 9):  [CatholicFeast("Saint Teresa Benedicta of The Cross (Edith Stein), Virgin and Martyr, Patron of Europe", _O)],
    (8, 10): [CatholicFeast("Saint Lawrence of Rome, Deacon and Martyr", _F)],
    (8, 11): [CatholicFeast("Saint Clare, Virgin", _M)],
    (8, 12): [CatholicFeast("Saint Jane Frances de Chantal, Religious", _O)],
    (8, 13): [CatholicFeast("Saints Pontian, Pope and Hippolytus, Priest, Martyrs", _O)],
    (8, 14): [CatholicFeast("Saint Maximilian Mary Kolbe, Priest and Martyr", _M)],
    (8, 15): [CatholicFeast("The Assumption of the Blessed Virgin Mary", _S)],
    (8, 16): [CatholicFeast("Saint Stephen of Hungary", _O)],
    (8, 19): [CatholicFeast("Saint John Eudes, Priest", _O)],
    (8, 20): [CatholicFeast("Saint Bernard of Clairvaux, Abbot and Doctor of the Church", _M)],
    (8, 21): [CatholicFeast("Saint Pius X, Pope", _O)],
    (8, 22): [CatholicFeast("Queenship of the Blessed Virgin Mary", _M)],
    (8, 23): [CatholicFeast("Saint Rose of Lima, Virgin", _O)],
    (8, 24): [CatholicFeast("Saint Bartholomew, Apostle", _F)],
    (8, 25): [CatholicFeast("Saint Louis/Saint Joseph of Calasanz, Priest", _O)],
    (8, 27): [CatholicFeast("Saint Monica", _M)],
    (8, 28): [CatholicFeast("Saint Augustine of Hippo, Bishop and Doctor of the Church", _M)],
    (8, 29): [CatholicFeast("Martyrdom of Saint John the Baptist", _M)],
    # September
    (9, 3):  [CatholicFeast("Saint Gregory the Great, Pope and Doctor of the Church", _M)],
    (9, 8):  [CatholicFeast("Birth of the Blessed Virgin Mary", _F)],
    (9, 9):  [CatholicFeast("Saint Peter Claver, Priest", _O)],
    (9, 12): [CatholicFeast("Holy Name of the Blessed Virgin Mary", _O)],
    (9, 13): [CatholicFeast("Saint John Chrysostom, Bishop and Doctor of the Church", _M)],
    (9, 14): [CatholicFeast("The Exaltation of the Holy Cross", _F)],
    (9, 15): [CatholicFeast("Our Lady of Sorrows", _M)],
    (9, 16): [CatholicFeast("Saints Cornelius, Pope, and Cyprian, Bishop, Martyrs", _M)],
    (9, 17): [CatholicFeast("Saint Robert Bellarmine, Bishop and Doctor of the Church", _O)],
    (9, 19): [CatholicFeast("Saint Januarius, Bishop and Martyr", _O)],
    (9, 20): [CatholicFeast("Saint Andrew Kim Taegon, Priest, and Paul Chong Hasang and Companions, Martyrs", _M)],
    (9, 21): [CatholicFeast("Saint Matthew, Apostle and Evangelist", _F)],
    (9, 23): [CatholicFeast("Saint Pio of Pietrelcina (Padre Pio), Priest", _M)],
    (9, 26): [CatholicFeast("Saints Cosmas and Damian, Martyrs", _O)],
    (9, 27): [CatholicFeast("Saint Vincent de Paul, Priest", _M)],
    (9, 28): [CatholicFeast("Saint Wenceslaus, Martyr/Saints Lawrence Ruiz and Companions, Martyrs", _O)],
    (9, 29): [CatholicFeast("Saints Michael, Gabriel and Raphael, Archangels", _F)],
    (9, 30): [CatholicFeast("Saint Jerome, Priest and Doctor", _M)],
    # October
    (10, 1):  [CatholicFeast("Saint Therese of the Child Jesus, Virgin and Doctor", _M)],
    (10, 2):  [CatholicFeast("Holy Guardian Angels", _M)],
    (10, 4):  [CatholicFeast("Saint Francis of Assisi", _M)],
    (10, 6):  [CatholicFeast("Saint Bruno, Priest", _O)],
    (10, 7):  [CatholicFeast("Our Lady of the Rosary", _M)],
    (10, 9):  [CatholicFeast("Saint Denis and Companions Martyrs/Saint John Leonardi, Priest", _O)],
    (10, 11): [CatholicFeast("Pope Saint John XXIII", _O)],
    (10, 14): [CatholicFeast("Saint Callistus I, Pope and Martyr", _O)],
    (10, 15): [CatholicFeast("Saint Teresa of Jesus, Virgin and Doctor", _M)],
    (10, 16): [CatholicFeast("Saint Hedwig, Religious/Saint Margaret Mary Alacoque, Virgin", _O)],
    (10, 17): [CatholicFeast("Saint Ignatius of Antioch, Bishop and Martyr", _M)],
    (10, 18): [CatholicFeast("Saint Luke the Evangelist", _F)],
    (10, 19): [CatholicFeast("Saints Jean de Brebeuf and Isaac Jogues, Priests and Companions, Martyrs", _O)],
    (10, 20): [CatholicFeast("Saint Paul of the Cross, Priest", _O)],
    (10, 22): [CatholicFeast("Pope Saint John Paul II", _O)],
    (10, 23): [CatholicFeast("Saint John of Capistrano, Priest", _O)],
    (10, 24): [CatholicFeast("Saint Anthony Mary Claret, Bishop", _O)],
    (10, 28): [CatholicFeast("Saints Simon and Jude, Apostles", _F)],
    # November
    (11, 1):  [CatholicFeast("All Saints", _S)],
    (11, 2):  [CatholicFeast("All Souls", _S)],
    (11, 3):  [CatholicFeast("Saint Martin de Porres, Religious", _M)],
    (11, 4):  [CatholicFeast("Saint Charles Borromeo, Bishop", _M)],
    (11, 9):  [CatholicFeast("Dedication of the Lateran Basilica", _F)],
    (11, 10): [CatholicFeast("Saint Leo the Great, Pope and Doctor", _M)],
    (11, 11): [CatholicFeast("Saint Martin of Tours, Bishop", _M)],
    (11, 12): [CatholicFeast("Saint Josaphat, Bishop and Martyr", _M)],
    (11, 15): [CatholicFeast("Saint Albert the Great, Bishop and Doctor", _O)],
    (11, 16): [CatholicFeast("Saint Margaret of Scotland/Saint Gertrude the Great, Virgin", _O)],
    (11, 17): [CatholicFeast("Saint Elizabeth of Hungary", _M)],
    (11, 18): [CatholicFeast("Dedication of the basilicas of Saints Peter and Paul, Apostles", _O)],
    (11, 21): [CatholicFeast("Presentation of the Blessed Virgin Mary", _M)],
    (11, 22): [CatholicFeast("Saint Cecilia, Virgin and Martyr", _M)],
    (11, 23): [CatholicFeast("Saint Clement I, Pope and Martyr/Saint Columban, Religious", _O)],
    (11, 24): [CatholicFeast("Saint Andrew Dung-Lac and Companions, Martyrs", _M)],
    (11, 25): [CatholicFeast("Saint Catherine of Alexandria, Virgin and Martyr", _O)],
    (11, 30): [CatholicFeast("Saint Andrew the Apostle", _F)],
    # December
    (12, 3):  [CatholicFeast("Saint Francis Xavier, Priest", _M)],
    (12, 4):  [CatholicFeast("Saint John Damascene, Priest and Doctor", _O)],
    (12, 6):  [CatholicFeast("Saint Nicholas, Bishop", _O)],
    (12, 7):  [CatholicFeast("Saint Ambrose, Bishop and Doctor", _M)],
    (12, 8):  [CatholicFeast("Immaculate Conception", _S)],
    (12, 9):  [CatholicFeast("Saint Juan Diego", _O)],
    (12, 11): [CatholicFeast("Saint Damasus I, Pope", _O)],
    (12, 12): [CatholicFeast("Our Lady of Guadalupe", _F)],
    (12, 13): [CatholicFeast("Saint Lucy of Syracuse, Virgin and Martyr", _M)],
    (12, 14): [CatholicFeast("Saint John of the Cross, Priest and Doctor", _M)],
    (12, 21): [CatholicFeast("Saint Peter Canisius, Priest and Doctor", _O)],
    (12, 23): [CatholicFeast("Saint John of Kenty, Priest", _O)],
    (12, 25): [CatholicFeast("Christmas", _S)],
    (12, 26): [CatholicFeast("Saint Stephen, The First Martyr", _F)],
    (12, 27): [CatholicFeast("Saint John the Apostle and Evangelist", _F)],
    (12, 28): [CatholicFeast("Holy Innocents, Martyrs", _F)],
    (12, 29): [CatholicFeast("Saint Thomas Becket, Bishop and Martyr", _O)],
    (12, 31): [CatholicFeast("Saint Sylvester I, Pope", _O)],
}


# ---------------------------------------------------------------------------
# Moveable feast computation
# ---------------------------------------------------------------------------

def _sunday_after(d: date) -> date:
    """Return the first Sunday strictly after d."""
    days_ahead = 6 - d.weekday()  # weekday(): Mon=0 … Sun=6
    if days_ahead <= 0:
        days_ahead += 7
    return d + timedelta(days=days_ahead)


def _sunday_on_or_after(d: date) -> date:
    days_ahead = (6 - d.weekday()) % 7
    return d + timedelta(days=days_ahead)


def _advent_start(year: int) -> date:
    """First Sunday of Advent = 4th Sunday before Dec 25."""
    christmas = date(year, 12, 25)
    # Find Sunday on or before Dec 25, then go back 3 more Sundays
    last_advent_sun = christmas - timedelta(days=(christmas.weekday() + 1) % 7)
    return last_advent_sun - timedelta(weeks=3)


def get_moveable_feasts(year: int) -> dict[date, list[CatholicFeast]]:
    """Return all moveable feasts for the given year, keyed by date."""
    e = easter_date(year)
    feasts: dict[date, list[CatholicFeast]] = {}

    def add(d: date, feast: CatholicFeast) -> None:
        feasts.setdefault(d, []).append(feast)

    # Pre-Easter
    add(e - timedelta(46), CatholicFeast("Ash Wednesday", _S))
    add(e - timedelta(7),  CatholicFeast("Palm Sunday", _S))
    add(e - timedelta(3),  CatholicFeast("Holy Thursday", _S))
    add(e - timedelta(2),  CatholicFeast("Good Friday", _S))
    add(e - timedelta(1),  CatholicFeast("Holy Saturday", _S))

    # Easter and octave
    add(e,                  CatholicFeast("Easter Sunday", _S))
    for i in range(1, 7):
        names = ["Easter Monday", "Easter Tuesday", "Easter Wednesday",
                 "Easter Thursday", "Easter Friday", "Easter Saturday"]
        add(e + timedelta(i), CatholicFeast(names[i - 1], _S))

    add(e + timedelta(7),  CatholicFeast("Divine Mercy Sunday", _S))

    # Ascension (universal calendar: Thursday = day 39)
    add(e + timedelta(39), CatholicFeast("Ascension of the Lord", _S))

    # Pentecost and following
    add(e + timedelta(49), CatholicFeast("Pentecost Sunday", _S))
    add(e + timedelta(50), CatholicFeast("Mary, Mother of The Church", _M))
    add(e + timedelta(56), CatholicFeast("Trinity Sunday", _S))
    add(e + timedelta(60), CatholicFeast("Corpus Christi", _S))
    add(e + timedelta(68), CatholicFeast("Sacred Heart of Jesus", _S))
    add(e + timedelta(69), CatholicFeast("Immaculate Heart of Mary", _M))

    # Christ the King: last Sunday before Advent
    advent = _advent_start(year)
    add(advent - timedelta(7), CatholicFeast("Christ the King", _S))

    # Holy Family: Sunday after Christmas; if none before Jan 1 → Dec 30
    christmas = date(year, 12, 25)
    holy_family = _sunday_after(christmas)
    if holy_family.year != year:
        holy_family = date(year, 12, 30)
    add(holy_family, CatholicFeast("Holy Family of Jesus, Mary and Joseph", _F))

    # Baptism of the Lord: Sunday after Epiphany (Jan 6)
    epiphany = date(year, 1, 6)
    add(_sunday_after(epiphany), CatholicFeast("Baptism of the Lord", _F))

    return feasts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Ranks that we consider "real" feasts (not a generic day)
_REAL_RANKS = {"SOLEMNITY", "FEAST", "MEMORIAL", "OPT_MEMORIAL"}

# Moveable entries that are season/structure labels rather than displayable
# feasts. Holy Week and Easter Triduum are handled by the HOLY_WEEK branch
# in the combined calendar. The octave weekdays have no named saint.
# Everything else (Corpus Christi, Sacred Heart, Christ the King, etc.)
# is a real feast and flows through normally.
_STRUCTURAL_NAMES: frozenset[str] = frozenset({
    "Ash Wednesday",
    "Palm Sunday",
    "Holy Thursday",
    "Good Friday",
    "Holy Saturday",
    "Easter Sunday",
    "Easter Monday",
    "Easter Tuesday",
    "Easter Wednesday",
    "Easter Thursday",
    "Easter Friday",
    "Easter Saturday",
})


def get_catholic_feasts(d: date) -> list[CatholicFeast]:
    """Return displayable Catholic feast(s) for date d.

    Returns an empty list on ferial days and on days whose only feast is a
    structural liturgical marker (e.g. Ash Wednesday, Easter Sunday).
    High-ranking moveable feasts suppress lower-ranked fixed feasts.
    """
    moveable = get_moveable_feasts(d.year)
    moveable_today = moveable.get(d, [])
    fixed_today = FIXED.get((d.month, d.day), [])

    # Find the highest moveable rank on this day
    max_moveable_rank = max(
        (f.rank_value for f in moveable_today), default=0
    )

    result: list[CatholicFeast] = []

    # Include moveable feasts that are NOT structural labels
    for feast in moveable_today:
        if feast.name not in _STRUCTURAL_NAMES:
            result.append(feast)

    # Include fixed feasts only if they aren't suppressed by a higher-ranked
    # moveable feast (solemnity or feast outranks memorial/opt_memorial)
    for feast in fixed_today:
        if max_moveable_rank >= 3:  # FEAST or SOLEMNITY present
            if feast.rank_value < max_moveable_rank:
                continue  # suppressed
        result.append(feast)

    return result
