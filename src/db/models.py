"""Legal knowledge base schema.

Entities:

- ``Court``           a judicial institution (Gjykata Kushtetuese, Gjykata e
                     Lartë, apeli, rrethi, administrative, ...)
- ``Person``          a human with any role in the legal system — judges,
                     prosecutors, lawyers. One person, one row, even if
                     they have played multiple roles across years.
- ``Affiliation``     which court a person is (or was) attached to.
- ``Case``            a single court decision. One row per decision.
- ``Participation``   link between a case and a person (judge / defense /
                     prosecution / party). Normalized so we can answer
                     "how many cases has lawyer X defended?" in one query.
- ``ArticleCited``    which articles of which codes a case cites.

Intelligence tables (per the founder's brief — data are public records):

- ``VettingRecord``     KPK / KPA vetting outcomes for judges / prosecutors.
- ``DisciplinaryAction`` KLGj / KLP / ILDKP / Dhoma Avokatisë sanctions.
- ``AssetDeclaration``   ILDKP patrimonio declarations with discrepancies.
- ``CriminalProceeding`` proceedings opened against a judge / prosecutor.

Operational:

- ``ScrapeJob``       one row per scraper run, for idempotency + resumes.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ──────────────────────────────────────────────────────────────────────
# Core tables
# ──────────────────────────────────────────────────────────────────────


class Court(Base):
    __tablename__ = "courts"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    # e.g. "apel_tirane", "shkalla_pare_tirane", "gjykata_e_larte_penal"
    name: Mapped[str] = mapped_column(String(200))
    level: Mapped[str] = mapped_column(String(40))
    # kushtetuese | larte | apel | shkalla_pare | administrative | ushtarake
    city: Mapped[str | None] = mapped_column(String(80))
    source_url: Mapped[str | None] = mapped_column(Text)

    cases: Mapped[list["Case"]] = relationship(back_populates="court")
    affiliations: Mapped[list["Affiliation"]] = relationship(back_populates="court")


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(200), index=True)
    # All surface spellings we've seen — "Luan Daçi", "L. Daçi", "Luan DACI".
    # Used by the name-normalization job when matching new scrapes.
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    # Can be multiple: a former prosecutor now in private practice has both.
    roles: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    # role codes: judge | prosecutor | lawyer | expert | witness
    birth_year: Mapped[int | None]
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    affiliations: Mapped[list["Affiliation"]] = relationship(back_populates="person")
    participations: Mapped[list["Participation"]] = relationship(back_populates="person")
    vetting_records: Mapped[list["VettingRecord"]] = relationship(back_populates="person")
    disciplinary_actions: Mapped[list["DisciplinaryAction"]] = relationship(back_populates="person")


class Affiliation(Base):
    __tablename__ = "affiliations"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    court_id: Mapped[int | None] = mapped_column(ForeignKey("courts.id"), index=True)
    # For lawyers: bar association chamber instead of a court. Nullable
    # court_id + chamber_code lets us model both.
    chamber_code: Mapped[str | None] = mapped_column(String(60))
    role: Mapped[str] = mapped_column(String(40))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    # Why they left (if end_date set): retired | dismissed | suspended |
    # resigned | term_ended | deceased
    status: Mapped[str] = mapped_column(String(40), default="active")
    source_url: Mapped[str | None] = mapped_column(Text)

    person: Mapped["Person"] = relationship(back_populates="affiliations")
    court: Mapped["Court | None"] = relationship(back_populates="affiliations")


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    court_id: Mapped[int] = mapped_column(ForeignKey("courts.id"), index=True)
    case_number: Mapped[str] = mapped_column(String(100))  # nr. çështjeje
    decision_date: Mapped[date | None] = mapped_column(Date, index=True)
    filing_date: Mapped[date | None] = mapped_column(Date)
    type: Mapped[str] = mapped_column(String(40), index=True)
    # penal | civil | administrative | family | labor | commercial | other
    subtype: Mapped[str | None] = mapped_column(String(80))
    outcome: Mapped[str | None] = mapped_column(String(40), index=True)
    # Outcomes we normalize to (so win-rate queries are possible):
    # convicted | acquitted | dismissed | partially_accepted | accepted |
    # rejected | remanded | modified | settled | other
    summary: Mapped[str | None] = mapped_column(Text)
    full_text: Mapped[str | None] = mapped_column(Text)
    raw_path: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime)
    # pending = only scraped, no LLM extraction yet
    # partial = text extracted, structured metadata missing
    # complete = judges/parties/articles all populated
    # failed = extraction failed, see notes
    extraction_status: Mapped[str] = mapped_column(String(20), default="pending")
    extraction_notes: Mapped[str | None] = mapped_column(Text)

    court: Mapped["Court"] = relationship(back_populates="cases")
    participations: Mapped[list["Participation"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    articles_cited: Mapped[list["ArticleCited"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("court_id", "case_number", name="uq_case_court_number"),
        Index("ix_cases_type_outcome", "type", "outcome"),
    )


class CaseAnalysis(Base):
    """Structured ratio decidendi for a case — what won, what lost, what to imitate.

    Populated by ``src/extract/ratio.py`` via Opus over ``Case.full_text``. One
    row per case, idempotent (UNIQUE on case_id). The Precedent Pattern
    Analyzer reads these rows to synthesize "moves to imitate / traps to
    avoid" for a current case dossier.

    Fields are written in shqip — the output is for an Albanian lawyer.
    """

    __tablename__ = "case_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id"), unique=True, index=True,
    )
    # The single argument that decided the case in the winner's favor.
    # 1-3 sentences, in shqip, anchored to a specific neni or fact.
    winning_argument: Mapped[str | None] = mapped_column(Text)
    # The procedural / substantive error the losing party made (or
    # equivalently, the gap in their argument). Empty if not identifiable
    # (some decisions are won purely on substantive grounds with no
    # opposing-counsel "mistake" to point to).
    losing_mistake: Mapped[str | None] = mapped_column(Text)
    # The single fact that pendulated the balance. Often a date, a
    # document, a piece of evidence — the thing without which the
    # outcome would have been different.
    dispositive_fact: Mapped[str | None] = mapped_column(Text)
    # 1-2 sentences of actionable lesson — what should an avvocato do
    # in a similar case (imitate or avoid).
    transferable_lesson: Mapped[str | None] = mapped_column(Text)
    # A short archetype label for matching: "kontestim_testamenti",
    # "ankim_jashteafati", "shpronesim_publik", etc. Free-form but
    # constrained to lowercase + underscores by the prompt.
    case_archetype: Mapped[str | None] = mapped_column(String(80), index=True)

    extracted_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    # pending | complete | failed
    extraction_status: Mapped[str] = mapped_column(String(20), default="pending")
    extraction_notes: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(40))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0"))

    case: Mapped["Case"] = relationship()


class Participation(Base):
    __tablename__ = "participations"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    # judge | defense | prosecution | plaintiff | defendant | expert | witness
    role: Mapped[str] = mapped_column(String(40), index=True)
    # True for the presiding judge (kryetar i trupit gjykues)
    presiding: Mapped[bool] = mapped_column(Boolean, default=False)
    # Client name / party the lawyer represented, if applicable
    representing: Mapped[str | None] = mapped_column(String(200))

    case: Mapped["Case"] = relationship(back_populates="participations")
    person: Mapped["Person"] = relationship(back_populates="participations")


class ArticleCited(Base):
    __tablename__ = "articles_cited"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    # Code slug matching src/config.LEGAL_DOCUMENTS.code (kodi_penal,
    # kodi_proc_civile, kushtetuta, ...)
    code: Mapped[str] = mapped_column(String(40))
    # "76", "76/2", "76/ç". Stored as-is from the text.
    article: Mapped[str] = mapped_column(String(30))
    paragraph: Mapped[str | None] = mapped_column(String(20))
    # A short excerpt from around the citation — helps the brain cite the
    # reasoning context, not just the bare number.
    context: Mapped[str | None] = mapped_column(Text)

    case: Mapped["Case"] = relationship(back_populates="articles_cited")

    __table_args__ = (Index("ix_ac_code_article", "code", "article"),)


# ──────────────────────────────────────────────────────────────────────
# Intelligence tables (public-records only)
# ──────────────────────────────────────────────────────────────────────


class VettingRecord(Base):
    """KPK / KPA vetting decision for a judge or prosecutor.

    Vetting criteria (all three are independently assessable):
      - ``pasuria``      declared wealth consistent with income?
      - ``integriteti``  links to organized crime / inappropriate ties?
      - ``profesional``  professional competence demonstrated?
    """

    __tablename__ = "vetting_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    # KPK (Komisioni i Pavarur i Kualifikimit, first instance) |
    # KPA (Kolegji i Posaçëm i Apelimit, appeal)
    source: Mapped[str] = mapped_column(String(20))
    # confirmed | confirmed_with_reserves | dismissed | resigned |
    # suspended | pending_appeal
    result: Mapped[str] = mapped_column(String(40))
    decision_date: Mapped[date | None] = mapped_column(Date)
    grounds: Mapped[str | None] = mapped_column(Text)
    # pass | fail | inconclusive — one per criterion (null if not assessed)
    pasuria_rating: Mapped[str | None] = mapped_column(String(20))
    integriteti_rating: Mapped[str | None] = mapped_column(String(20))
    profesional_rating: Mapped[str | None] = mapped_column(String(20))
    decision_url: Mapped[str | None] = mapped_column(Text)
    reasoning_excerpt: Mapped[str | None] = mapped_column(Text)

    person: Mapped["Person"] = relationship(back_populates="vetting_records")


class DisciplinaryAction(Base):
    __tablename__ = "disciplinary_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    # KLGj (judges) | KLP (prosecutors) | ILDKP (asset-declaration
    # violations) | Dhoma_Avokatise (bar-association actions on lawyers)
    source: Mapped[str] = mapped_column(String(40))
    action_date: Mapped[date | None] = mapped_column(Date)
    # warning | reprimand | fine | salary_cut | suspension | demotion |
    # dismissal | disbarment
    action_type: Mapped[str] = mapped_column(String(40))
    grounds: Mapped[str | None] = mapped_column(Text)
    decision_url: Mapped[str | None] = mapped_column(Text)
    # True while the sanction is still in effect (e.g. suspension ongoing)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    person: Mapped["Person"] = relationship(back_populates="disciplinary_actions")


class AssetDeclaration(Base):
    __tablename__ = "asset_declarations"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    year: Mapped[int]
    total_declared: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # ILDKP's own assessment of what portion couldn't be justified.
    unjustified_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # reviewed_clean | under_verification | referred_prosecution | dismissed
    ildkp_status: Mapped[str | None] = mapped_column(String(40))
    source_url: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("person_id", "year", name="uq_asset_person_year"),
    )


class CriminalProceeding(Base):
    """A criminal proceeding *opened against* a judge or prosecutor."""

    __tablename__ = "criminal_proceedings"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    # under_investigation | indicted | trial | convicted | acquitted |
    # dismissed | statute_expired
    status: Mapped[str] = mapped_column(String(40))
    charges: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    # If the proceeding is itself a case we have in this DB, link it.
    reference_case_id: Mapped[int | None] = mapped_column(
        ForeignKey("cases.id"), index=True
    )
    opened_date: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


# ──────────────────────────────────────────────────────────────────────
# Operational
# ──────────────────────────────────────────────────────────────────────


class ScrapeJob(Base):
    """One row per scraper run. Lets us resume after crashes."""

    __tablename__ = "scrape_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    scraper: Mapped[str] = mapped_column(String(80), index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    # running | completed | failed | interrupted
    status: Mapped[str] = mapped_column(String(20), default="running")
    cases_found: Mapped[int] = mapped_column(Integer, default=0)
    cases_new: Mapped[int] = mapped_column(Integer, default=0)
    cases_skipped: Mapped[int] = mapped_column(Integer, default=0)
    last_url: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
