"""Candidate schemes Haq knows how to research: central + Uttar Pradesh.

This is a planning aid, not the source of truth. Every eligibility rule and
amount is re-verified on an official page at run time; the URLs here are the
starting points and the official fallbacks used when a lookup fails.
"""
from urllib.parse import urlparse

OFFICIAL_SUFFIXES = (".gov.in", ".nic.in")
OFFICIAL_HOSTS = {
    "maandhan.in",          # Ministry of Labour & Employment (PM-SYM / PM-KMY)
    "upbocw.in",            # UP Building & Other Construction Workers Welfare Board
    "mudra.org.in",
}


def is_official(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host in OFFICIAL_HOSTS or host.endswith(OFFICIAL_SUFFIXES) or host in {"gov.in", "nic.in"}


SCHEMES = [
    # ---------------- Central ----------------
    {
        "id": "pm_kisan", "level": "central", "emoji": "🌾",
        "name_hi": "पीएम किसान सम्मान निधि", "name_en": "PM-KISAN",
        "hint": "Land-owning farmer families; Rs 6,000/yr in 3 instalments. Excludes income-tax payers, govt employees, pensioners >=10k/month, professionals.",
        "official_urls": ["https://pmkisan.gov.in/"],
        "fallback_urls": ["https://www.myscheme.gov.in/schemes/pm-kisan", "https://agriwelfare.gov.in/"],
        "aliases": ["pmkisan", "pm-kisan"],
    },
    {
        "id": "pmjay", "level": "central", "emoji": "🏥",
        "name_hi": "आयुष्मान भारत (PM-JAY)", "name_en": "Ayushman Bharat PM-JAY",
        "hint": "Rs 5 lakh/family/yr cashless hospital cover for SECC-deprived / NFSA (Antyodaya, eligible household ration card) families; in UP also linked to ration cards.",
        "official_urls": ["https://nha.gov.in/PM-JAY", "https://beneficiary.nha.gov.in/"],
        "fallback_urls": ["https://pmjay.gov.in/", "https://www.myscheme.gov.in/schemes/ab-pmjay"],
        "aliases": ["ayushman_bharat", "ab_pmjay", "ayushman"],
    },
    {
        "id": "ayushman_vay_vandana", "level": "central", "emoji": "👴",
        "name_hi": "आयुष्मान वय वंदना (70+)", "name_en": "Ayushman Vay Vandana (PM-JAY 70+)",
        "hint": "Every citizen aged 70+ gets Rs 5 lakh/yr health cover regardless of income.",
        "official_urls": ["https://beneficiary.nha.gov.in/", "https://nha.gov.in/PM-JAY"],
        "fallback_urls": ["https://www.myscheme.gov.in/schemes/abpmjayvv"],
        "aliases": ["vay_vandana", "pmjay_70"],
    },
    {
        "id": "pmay_g", "level": "central", "emoji": "🏠",
        "name_hi": "प्रधानमंत्री आवास योजना (ग्रामीण)", "name_en": "PMAY-Gramin",
        "hint": "Rural homeless / kutcha-house families; Rs 1.2 lakh (plains) one-time for a pucca house.",
        "official_urls": ["https://pmayg.dord.gov.in/"],
        "rules_docs": ["https://pmayg.dord.gov.in/netiayHome/Uploaded/Guidelines-English_Book_Final.pdf"],
        "fallback_urls": ["https://pmayg.nic.in/", "https://www.myscheme.gov.in/schemes/pmay-g"],
        "aliases": ["pmayg", "awas_gramin"],
    },
    {
        "id": "pmuy", "level": "central", "emoji": "🔥",
        "name_hi": "प्रधानमंत्री उज्ज्वला योजना", "name_en": "PM Ujjwala Yojana",
        "hint": "Free LPG connection for adult woman of poor household (SC/ST, PMAY-G, AAY, etc.) with no LPG connection in the household.",
        "official_urls": ["https://pmuy.gov.in/"],
        "fallback_urls": ["https://www.myscheme.gov.in/schemes/pmuy"],
        "aliases": ["ujjwala"],
    },
    {
        "id": "pmmvy", "level": "central", "emoji": "🤱",
        "name_hi": "प्रधानमंत्री मातृ वंदना योजना", "name_en": "PM Matru Vandana Yojana",
        "hint": "Pregnant / lactating women: Rs 5,000 for first child, Rs 6,000 if second child is a girl.",
        "official_urls": ["https://pmmvy.wcd.gov.in/"],
        "fallback_urls": ["https://wcd.gov.in/", "https://www.myscheme.gov.in/schemes/pmmvy"],
        "aliases": ["matru_vandana"],
    },
    {
        "id": "nfsa_ration", "level": "central", "emoji": "🍚",
        "name_hi": "राशन कार्ड (मुफ्त अनाज, NFSA)", "name_en": "NFSA ration / PMGKAY free grain",
        "hint": "Free 5 kg grain/person/month for priority households; 35 kg/family for Antyodaya. UP applications via fcs.up.gov.in.",
        "official_urls": ["https://nfsa.gov.in/", "https://fcs.up.gov.in/"],
        "fallback_urls": ["https://dfpd.gov.in/"],
        "aliases": ["ration_card", "pmgkay", "nfsa"],
    },
    {
        "id": "pm_sym", "level": "central", "emoji": "🧓",
        "name_hi": "प्रधानमंत्री श्रम योगी मानधन", "name_en": "PM Shram Yogi Maandhan",
        "hint": "Unorganised workers aged 18-40 with income up to Rs 15,000/month; contributory, Rs 3,000/month pension at 60.",
        "official_urls": ["https://maandhan.in/"],
        "fallback_urls": ["https://www.myscheme.gov.in/schemes/pmsym", "https://labour.gov.in/"],
        "aliases": ["pmsym", "shram_yogi_maandhan"],
    },
    {
        "id": "pm_kisan_maandhan", "level": "central", "emoji": "🌱",
        "name_hi": "प्रधानमंत्री किसान मानधन", "name_en": "PM Kisan Maandhan",
        "hint": "Small/marginal farmers aged 18-40; contributory, Rs 3,000/month pension at 60.",
        "official_urls": ["https://maandhan.in/"],
        "fallback_urls": ["https://www.myscheme.gov.in/schemes/pmkmy", "https://pmkisan.gov.in/"],
        "aliases": ["pmkmy"],
    },
    {
        "id": "pmjjby", "level": "central", "emoji": "🛡️",
        "name_hi": "प्रधानमंत्री जीवन ज्योति बीमा", "name_en": "PMJJBY",
        "hint": "Age 18-50 with bank account; Rs 2 lakh life cover for Rs 436/yr premium.",
        "official_urls": ["https://jansuraksha.gov.in/"],
        "fallback_urls": ["https://www.myscheme.gov.in/schemes/pmjjby"],
        "aliases": [],
    },
    {
        "id": "pmsby", "level": "central", "emoji": "🦺",
        "name_hi": "प्रधानमंत्री सुरक्षा बीमा", "name_en": "PMSBY",
        "hint": "Age 18-70 with bank account; Rs 2 lakh accident cover for Rs 20/yr premium.",
        "official_urls": ["https://jansuraksha.gov.in/"],
        "fallback_urls": ["https://www.myscheme.gov.in/schemes/pmsby"],
        "aliases": [],
    },
    {
        "id": "eshram", "level": "central", "emoji": "🪪",
        "name_hi": "ई-श्रम कार्ड", "name_en": "e-Shram registration",
        "hint": "Unorganised workers 16-59 not in EPFO/ESIC, not income-tax payers; free registration (UAN), gateway to welfare.",
        "official_urls": ["https://eshram.gov.in/"],
        "fallback_urls": ["https://labour.gov.in/"],
        "aliases": ["e_shram"],
    },
    {
        "id": "pmfby", "level": "central", "emoji": "☔",
        "name_hi": "प्रधानमंत्री फसल बीमा योजना", "name_en": "PM Fasal Bima Yojana",
        "hint": "Crop insurance for farmers (owners and tenants) growing notified crops; low premium.",
        "official_urls": ["https://pmfby.gov.in/"],
        "fallback_urls": ["https://www.myscheme.gov.in/schemes/pmfby"],
        "aliases": [],
    },
    {
        "id": "pm_vishwakarma", "level": "central", "emoji": "🔨",
        "name_hi": "पीएम विश्वकर्मा", "name_en": "PM Vishwakarma",
        "hint": "Artisans in 18 traditional trades (carpenter, potter, tailor, cobbler, barber, mason...) aged 18+; toolkit Rs 15,000 e-voucher, training stipend, cheap credit.",
        "official_urls": ["https://pmvishwakarma.gov.in/"],
        "fallback_urls": ["https://www.myscheme.gov.in/schemes/pmvs"],
        "aliases": ["vishwakarma"],
    },
    {
        "id": "nsp_scholarship", "level": "central", "emoji": "🎓",
        "name_hi": "राष्ट्रीय छात्रवृत्ति (NSP)", "name_en": "National Scholarship Portal schemes",
        "hint": "Central pre/post-matric and merit scholarships (SC/ST/OBC/minority/disabled students), income limits vary by scheme.",
        "official_urls": ["https://scholarships.gov.in/"],
        "fallback_urls": ["https://www.india.gov.in/"],
        "aliases": ["nsp"],
    },
    # ---------------- Uttar Pradesh ----------------
    {
        "id": "up_old_age_pension", "level": "up", "emoji": "🧓",
        "name_hi": "वृद्धावस्था पेंशन (उ.प्र.)", "name_en": "UP Old Age Pension (with NSAP IGNOAPS)",
        "hint": "UP residents aged 60+ below poverty line / within income limit; Rs 1,000/month via sspy-up.gov.in.",
        "official_urls": ["https://sspy-up.gov.in/"],
        "fallback_urls": ["https://nsap.nic.in/", "https://www.myscheme.gov.in/schemes/oaps-up"],
        "aliases": ["ignoaps", "old_age_pension", "vridha_pension"],
    },
    {
        "id": "up_widow_pension", "level": "up", "emoji": "🙏",
        "name_hi": "निराश्रित महिला (विधवा) पेंशन", "name_en": "UP Destitute Women (Widow) Pension",
        "hint": "Women 18+ whose husband has died, UP resident, family income within limit; Rs 1,000/month.",
        "official_urls": ["https://sspy-up.gov.in/"],
        "fallback_urls": ["https://mahilakalyan.up.nic.in/", "https://nsap.nic.in/"],
        "aliases": ["ignwps", "widow_pension", "nirashrit_mahila_pension"],
    },
    {
        "id": "up_divyang_pension", "level": "up", "emoji": "♿",
        "name_hi": "दिव्यांग पेंशन (उ.प्र.)", "name_en": "UP Divyang (Disability) Pension",
        "hint": "40%+ disability certificate, UP resident, income within limit; Rs 1,000/month.",
        "official_urls": ["https://sspy-up.gov.in/"],
        "fallback_urls": ["https://divyangjan.upsdc.gov.in/", "https://nsap.nic.in/"],
        "aliases": ["igndps", "disability_pension", "viklang_pension"],
    },
    {
        "id": "up_kanya_sumangala", "level": "up", "emoji": "👧",
        "name_hi": "मुख्यमंत्री कन्या सुमंगला योजना", "name_en": "Mukhyamantri Kanya Sumangala Yojana",
        "hint": "Girls in UP families with income <= Rs 3 lakh, max 2 girls/family; Rs 25,000 over 6 stages (birth, vaccination, class 1, 6, 9, graduation/diploma).",
        "official_urls": ["https://mksy.up.gov.in/"],
        "fallback_urls": ["https://www.myscheme.gov.in/schemes/mksy", "https://mahilakalyan.up.nic.in/"],
        "aliases": ["kanya_sumangala", "mksy"],
    },
    {
        "id": "up_shadi_anudan", "level": "up", "emoji": "💍",
        "name_hi": "शादी अनुदान योजना", "name_en": "UP Shadi Anudan (marriage grant)",
        "hint": "Rs 20,000 for marriage of daughter (18+) of poor families; income limit Rs 46,460 rural / Rs 56,460 urban (SC/ST/General), Rs 1 lakh for OBC.",
        "official_urls": ["https://shadianudan.upsdc.gov.in/"],
        "fallback_urls": ["https://www.myscheme.gov.in/"],
        "aliases": ["shadi_anudan"],
    },
    {
        "id": "up_samuhik_vivah", "level": "up", "emoji": "💒",
        "name_hi": "मुख्यमंत्री सामूहिक विवाह योजना", "name_en": "Mukhyamantri Samuhik Vivah Yojana",
        "hint": "Mass marriage for daughters / widows of needy families; Rs 1 lakh per couple (Rs 64,000 to bride's account).",
        "official_urls": ["https://cmsvy.upsdc.gov.in/"],
        "fallback_urls": ["https://www.myscheme.gov.in/"],
        "aliases": ["samuhik_vivah"],
    },
    {
        "id": "up_scholarship", "level": "up", "emoji": "📚",
        "name_hi": "उ.प्र. छात्रवृत्ति (पूर्व/उत्तर दशम)", "name_en": "UP Pre/Post-Matric Scholarship",
        "hint": "UP students class 9+ (pre-matric 9-10, post-matric 11+) of SC/ST/OBC/General/minority with family income within category limit.",
        "official_urls": ["https://scholarship.up.gov.in/"],
        "rules_docs": [
            "https://scholarship.up.gov.in/pdfs/go/OBC_Pre%20matrici%20Niyamawali%20(2016).pdf",
            "https://scholarship.up.gov.in/pdfs/SC%20NIYAMAVALI14%20OCTOBER%202019%20ENF%20BY%202020-21.pdf",
        ],
        "fallback_urls": ["https://scholarships.gov.in/"],
        "aliases": ["up_post_matric", "up_pre_matric"],
    },
    {
        "id": "up_bocw", "level": "up", "emoji": "👷",
        "name_hi": "भवन निर्माण श्रमिक पंजीकरण (BOCW)", "name_en": "UP BOCW construction worker welfare",
        "hint": "Construction workers 18-60 with 90 days work in last year; registration unlocks maternity, education, marriage, accident and housing benefits.",
        "official_urls": ["https://upbocw.in/"],
        "fallback_urls": ["https://www.myscheme.gov.in/"],
        "aliases": ["bocw", "shramik_panjikaran"],
    },
    {
        "id": "up_abhyudaya", "level": "up", "emoji": "🧑‍🎓",
        "name_hi": "मुख्यमंत्री अभ्युदय योजना", "name_en": "Mukhyamantri Abhyudaya Yojana",
        "hint": "Free coaching for competitive exams (UPSC, NEET, JEE...) for UP students.",
        "official_urls": ["https://abhyuday.up.gov.in/"],
        "fallback_urls": ["https://www.myscheme.gov.in/"],
        "aliases": ["abhyudaya"],
    },
    {
        "id": "up_digishakti", "level": "up", "emoji": "📱",
        "name_hi": "स्वामी विवेकानंद युवा सशक्तिकरण (टैबलेट/स्मार्टफोन)", "name_en": "UP DigiShakti free tablet/smartphone",
        "hint": "Free tablet/smartphone for UP students in graduation, PG, diploma, ITI, nursing etc. registered on DigiShakti.",
        "official_urls": ["https://digishakti.up.gov.in/"],
        "fallback_urls": ["https://www.myscheme.gov.in/"],
        "aliases": ["digishakti", "free_tablet"],
    },
]

# Names shown to families. Hindi uses the scheme's official Hindi name; well-known acronyms stay as they are.
DISPLAY_NAMES = {
    "pm_kisan": ("PM-KISAN", "PM-KISAN"),
    "pmjay": ("आयुष्मान भारत (PM-JAY)", "Ayushman Bharat (PM-JAY)"),
    "ayushman_vay_vandana": ("आयुष्मान वय वंदना योजना", "Ayushman Vay Vandana"),
    "pmay_g": ("PMAY-G", "PMAY-G"),
    "pmuy": ("प्रधानमंत्री उज्ज्वला योजना", "PM Ujjwala Yojana"),
    "pmmvy": ("प्रधानमंत्री मातृ वंदना योजना", "PM Matru Vandana Yojana"),
    "nfsa_ration": ("राष्ट्रीय खाद्य सुरक्षा योजना (राशन कार्ड)", "NFSA ration card"),
    "pm_sym": ("प्रधानमंत्री श्रम योगी मान-धन योजना", "PM Shram Yogi Maandhan"),
    "pm_kisan_maandhan": ("प्रधानमंत्री किसान मान-धन योजना", "PM Kisan Maandhan"),
    "pmjjby": ("PMJJBY", "PMJJBY"),
    "pmsby": ("PMSBY", "PMSBY"),
    "eshram": ("ई-श्रम कार्ड", "e-Shram card"),
    "pmfby": ("प्रधानमंत्री फसल बीमा योजना", "PM Fasal Bima Yojana"),
    "pm_vishwakarma": ("पीएम विश्वकर्मा योजना", "PM Vishwakarma"),
    "nsp_scholarship": ("राष्ट्रीय छात्रवृत्ति पोर्टल (NSP)", "National Scholarship Portal (NSP)"),
    "up_old_age_pension": ("वृद्धावस्था पेंशन योजना", "UP Old Age Pension"),
    "up_widow_pension": ("निराश्रित महिला पेंशन योजना", "UP Destitute Women Pension"),
    "up_divyang_pension": ("दिव्यांग पेंशन योजना", "UP Divyang Pension"),
    "up_kanya_sumangala": ("मुख्यमंत्री कन्या सुमंगला योजना", "Mukhyamantri Kanya Sumangala Yojana"),
    "up_shadi_anudan": ("शादी अनुदान योजना", "Shadi Anudan Yojana"),
    "up_samuhik_vivah": ("मुख्यमंत्री सामूहिक विवाह योजना", "Mukhyamantri Samuhik Vivah Yojana"),
    "up_scholarship": ("पूर्वदशम एवं दशमोत्तर छात्रवृत्ति (उ.प्र.)", "UP Pre/Post-Matric Scholarship"),
    "up_bocw": ("उ.प्र. भवन एवं अन्य सन्निर्माण कर्मकार कल्याण बोर्ड", "UP BOCW construction workers' welfare"),
    "up_abhyudaya": ("मुख्यमंत्री अभ्युदय योजना", "Mukhyamantri Abhyudaya Yojana"),
    "up_digishakti": ("स्वामी विवेकानंद युवा सशक्तिकरण योजना", "Swami Vivekanand Yuva Sashaktikaran (DigiShakti)"),
}

# Insurance the family pays a small premium for: shown as protection, never added to the money owed.
# Premium and cover as published on jansuraksha.gov.in.
PROTECTION = {
    "pmsby": {"premium_inr_per_year": 20, "cover_inr": 200000, "kind": "accident"},
    "pmjjby": {"premium_inr_per_year": 436, "cover_inr": 200000, "kind": "life"},
}

BY_ID = {s["id"]: s for s in SCHEMES}


def display_name(scheme_id: str, lang: str) -> str | None:
    names = DISPLAY_NAMES.get(scheme_id)
    return (names[0] if lang == "hi" else names[1]) if names else None
_ALIASES = {a: s["id"] for s in SCHEMES for a in s["aliases"]}


def canonical_id(scheme_id: str) -> str:
    sid = (scheme_id or "").strip().lower().replace("-", "_").replace(" ", "_")
    return sid if sid in BY_ID else _ALIASES.get(sid, sid)


def all_official_urls(scheme_id: str) -> list[str]:
    """Portal pages, then official rule documents (PDF guidelines / niyamawali), then other official pages."""
    s = BY_ID.get(canonical_id(scheme_id))
    return (s["official_urls"] + s.get("rules_docs", []) + s["fallback_urls"]) if s else []


def catalog_for_prompt() -> str:
    lines = []
    for s in SCHEMES:
        lines.append(f"- {s['id']} [{s['level']}] {s['name_en']}: {s['hint']}")
    return "\n".join(lines)
