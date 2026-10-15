"""The "Per {party}, " lead continues the sentence of the section body."""
from app.services.generation.integrator import lead_body, party_lead


def test_article_after_lead_goes_lower_case():
    assert party_lead("Lega - Salvini Premier", "Il gruppo si oppone.") == \
        "Per Lega - Salvini Premier, il gruppo si oppone."
    assert lead_body("L'esecutivo ha risposto.") == "l'esecutivo ha risposto."
    assert lead_body("Nel dibattito sul tema") == "nel dibattito sul tema"


def test_proper_nouns_keep_capital():
    assert lead_body("Giorgia Meloni ha detto") == "Giorgia Meloni ha detto"
    assert lead_body("Italia Viva sostiene") == "Italia Viva sostiene"
    assert lead_body("IV sostiene") == "IV sostiene"


def test_group_named_per_reads_naturally():
    from app.services.generation.integrator import readable_party_leads
    text = "Per Lega, il gruppo.\n\nPer Per le Autonomie (SVP-PATT, Campobase), il gruppo."
    assert readable_party_leads(text) == (
        "Per Lega, il gruppo.\n\n"
        "Per il gruppo Per le Autonomie (SVP-PATT, Campobase), il gruppo.")
