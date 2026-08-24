
"""Client PDF report for the standalone VARIO + battery comparator."""

from __future__ import annotations

from io import BytesIO
import math
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    KeepTogether, HRFlowable
)
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart

ORANGE = HexColor("#ef5b32")
DARK = HexColor("#111827")
MID = HexColor("#374151")
MUTED = HexColor("#6b7280")
LIGHT = HexColor("#f3f4f6")
GREEN = HexColor("#16a34a")
BLUE = HexColor("#2563eb")
PALE_GREEN = HexColor("#ecfdf5")
PALE_BLUE = HexColor("#eff6ff")
RED = HexColor("#dc2626")


def _money(v):
    return f"{float(v):,.0f}".replace(",", " ") + " CHF"


def _money2(v):
    return f"{float(v):,.2f}".replace(",", " ") + " CHF"


def _pct(v):
    return f"{float(v):.1f} %"


def _title_block(client_name, period_text, simulated):
    rows = [
        [Paragraph("<b>Analyse tarifaire Groupe E</b>", ParagraphStyle(
            "ttl", fontName="Helvetica-Bold", fontSize=21, textColor=colors.white, leading=24
        ))],
        [Paragraph("Comparaison Double / VARIO et potentiel d'une batterie",
                   ParagraphStyle("sub", fontName="Helvetica", fontSize=9.5, textColor=HexColor("#e5e7eb")))]
    ]
    if client_name:
        rows.append([Paragraph(f"Client / site : <b>{client_name}</b>",
                               ParagraphStyle("cli", fontName="Helvetica", fontSize=9.5, textColor=colors.white))])
    rows.append([Paragraph(f"Période analysée : <b>{period_text}</b>",
                           ParagraphStyle("per", fontName="Helvetica", fontSize=9.5, textColor=colors.white))])
    if simulated:
        rows.append([Paragraph(
            "SIMULATION : profil de charge 2025 transpose sur 2026 - prix VARIO reels 2026.",
            ParagraphStyle("sim", fontName="Helvetica-Bold", fontSize=8.5, textColor=HexColor("#fde68a"))
        )])

    t = Table(rows, colWidths=[180*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),DARK),
        ("LEFTPADDING",(0,0),(-1,-1),8*mm),
        ("RIGHTPADDING",(0,0),(-1,-1),8*mm),
        ("TOPPADDING",(0,0),(-1,0),6*mm),
        ("BOTTOMPADDING",(0,-1),(-1,-1),5*mm),
    ]))
    return t


def _kpi_table(items, cols=4):
    data=[]
    row=[]
    for label, value, sub, color in items:
        cell = Table([
            [Paragraph(label, ParagraphStyle("kl", fontName="Helvetica-Bold", fontSize=8.5, textColor=MID))],
            [Paragraph(value, ParagraphStyle("kv", fontName="Helvetica-Bold", fontSize=16, textColor=color))],
            [Paragraph(sub or "", ParagraphStyle("ks", fontName="Helvetica", fontSize=7.5, textColor=MUTED))]
        ], colWidths=[(180/cols-4)*mm])
        cell.setStyle(TableStyle([
            ("BOX",(0,0),(-1,-1),0.6,HexColor("#d1d5db")),
            ("BACKGROUND",(0,0),(-1,-1),colors.white),
            ("LEFTPADDING",(0,0),(-1,-1),4*mm),
            ("RIGHTPADDING",(0,0),(-1,-1),4*mm),
            ("TOPPADDING",(0,0),(-1,-1),3*mm),
            ("BOTTOMPADDING",(0,0),(-1,-1),3*mm),
        ]))
        row.append(cell)
        if len(row)==cols:
            data.append(row); row=[]
    if row:
        while len(row)<cols: row.append("")
        data.append(row)
    outer = Table(data, colWidths=[180/cols*mm]*cols, hAlign="LEFT")
    outer.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),1*mm),
                               ("RIGHTPADDING",(0,0),(-1,-1),1*mm),("TOPPADDING",(0,0),(-1,-1),1*mm),
                               ("BOTTOMPADDING",(0,0),(-1,-1),1*mm)]))
    return outer


def _scenario_bars(scenarios):
    # scenarios: [(label,cost)]
    maxv=max(v for _,v in scenarios) if scenarios else 1
    rows=[]
    for label,cost in scenarios:
        frac=max(0.03, cost/maxv if maxv else 0.03)
        barw=110*mm*frac
        bar = Table([[""]], colWidths=[barw], rowHeights=[6*mm])
        bar.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),BLUE)]))
        right = Paragraph(_money(cost), ParagraphStyle("rv",fontName="Helvetica-Bold",fontSize=10,textColor=DARK))
        labelp=Paragraph(label,ParagraphStyle("lb",fontName="Helvetica-Bold",fontSize=9,textColor=MID))
        rows.append([labelp,bar,right])
    t=Table(rows,colWidths=[42*mm,112*mm,26*mm],hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),2*mm),("BOTTOMPADDING",(0,0),(-1,-1),2*mm),
        ("LEFTPADDING",(0,0),(-1,-1),1*mm),("RIGHTPADDING",(0,0),(-1,-1),1*mm),
    ]))
    return t


def _monthly_chart(monthly_df, scenario_cols, scenario_labels):
    if monthly_df is None or monthly_df.empty:
        return None

    months=list(monthly_df["Mois"])
    drawing=Drawing(180*mm,78*mm)
    chart=VerticalBarChart()
    chart.x=12*mm; chart.y=16*mm; chart.height=52*mm; chart.width=158*mm
    chart.data=[list(monthly_df[c].astype(float).values) for c in scenario_cols]
    chart.categoryAxis.categoryNames=months
    chart.categoryAxis.labels.fontName="Helvetica"
    chart.categoryAxis.labels.fontSize=6.5
    chart.categoryAxis.labels.angle=30
    chart.valueAxis.labels.fontName="Helvetica"
    chart.valueAxis.labels.fontSize=6.5
    chart.valueAxis.valueMin=0
    chart.barSpacing=1
    chart.groupSpacing=4
    palette=[HexColor("#93c5fd"), HexColor("#2563eb"), HexColor("#fca5a5"), HexColor("#ef4444")]
    for i in range(len(chart.data)):
        chart.bars[i].fillColor=palette[i % len(palette)]
        chart.bars[i].strokeColor=None
    drawing.add(chart)

    # legend
    x=15*mm; y=4*mm
    for i,label in enumerate(scenario_labels):
        from reportlab.graphics.shapes import Rect, String
        drawing.add(Rect(x,y,4*mm,4*mm,fillColor=palette[i%len(palette)],strokeColor=None))
        drawing.add(String(x+5*mm,y+0.5*mm,label,fontName="Helvetica",fontSize=6.5,fillColor=MID))
        x += 38*mm
    return drawing


def generate_vario_report(
    *,
    client_name,
    period_start,
    period_end,
    period_days,
    profile_transposed,
    capacity_kwh,
    power_kw,
    efficiency,
    soc_min,
    soc_max,
    feed_in_ct,
    wear_ct,
    double_cost,
    vario_cost,
    vario_pv_bill,
    vario_pv_economic,
    arbitrage_enabled,
    vario_grid_bill=None,
    vario_grid_economic=None,
    cycles_annualized=0,
    monthly_df=None,
):
    bio=BytesIO()
    doc=SimpleDocTemplate(
        bio,pagesize=A4,
        rightMargin=15*mm,leftMargin=15*mm,topMargin=12*mm,bottomMargin=12*mm,
        title="Analyse tarifaire Groupe E - VARIO",
        author="Soleol"
    )
    styles=getSampleStyleSheet()
    H2=ParagraphStyle("h2",parent=styles["Heading2"],fontName="Helvetica-Bold",fontSize=13,
                      leading=16,textColor=DARK,spaceBefore=4*mm,spaceAfter=2.5*mm)
    BODY=ParagraphStyle("body",parent=styles["BodyText"],fontName="Helvetica",fontSize=9,
                        leading=13,textColor=MID)
    SMALL=ParagraphStyle("small",parent=BODY,fontSize=7.5,leading=10,textColor=MUTED)
    CALLOUT=ParagraphStyle("call",parent=BODY,fontName="Helvetica-Bold",fontSize=10.5,
                           leading=14,textColor=DARK)

    period_text=f"{pd.Timestamp(period_start):%d.%m.%Y} - {pd.Timestamp(period_end):%d.%m.%Y} ({period_days:.0f} jours)"
    story=[_title_block(client_name,period_text,profile_transposed),Spacer(1,5*mm)]

    best_bill = vario_grid_bill if arbitrage_enabled and vario_grid_bill is not None else vario_pv_bill
    best_econ = vario_grid_economic if arbitrage_enabled and vario_grid_economic is not None else vario_pv_economic

    gain_vario=double_cost-vario_cost
    gain_pv=vario_cost-vario_pv_bill
    gain_arb=(vario_pv_bill-vario_grid_bill) if arbitrage_enabled and vario_grid_bill is not None else 0
    gain_bill=double_cost-best_bill
    gain_net=double_cost-best_econ
    annual_bill=gain_bill*365/period_days if period_days else 0
    annual_net=gain_net*365/period_days if period_days else 0

    story.append(Paragraph("Synthese",H2))
    story.append(_kpi_table([
        ("Reduction de facture",_money(gain_bill),f"sur {period_days:.0f} jours",GREEN),
        ("Projection facture",f"{_money(annual_bill)}/an","annualisation indicative",GREEN),
        ("Gain net apres usure",_money(gain_net),f"usure {wear_ct:.1f} ct/kWh",BLUE),
        ("Cycles estimes",f"{cycles_annualized:.0f}/an","batterie simulee",MID),
    ],4))
    story.append(Spacer(1,4*mm))

    conclusion = (
        f"Le passage au tarif VARIO seul {'economise' if gain_vario>=0 else 'coute'} "
        f"<b>{_money(abs(gain_vario))}</b> sur la periode. "
        f"L'essentiel de la reduction de facture provient de la batterie : "
        f"<b>{_money(gain_pv)}</b> grace au stockage du surplus solaire."
    )
    if arbitrage_enabled:
        conclusion += f" Le pilotage VARIO avec arbitrage reseau apporte encore <b>{_money(gain_arb)}</b> de reduction de facture."
    story.append(Table([[Paragraph(conclusion,CALLOUT)]],colWidths=[180*mm],style=[
        ("BACKGROUND",(0,0),(-1,-1),PALE_GREEN),("BOX",(0,0),(-1,-1),0.7,GREEN),
        ("LEFTPADDING",(0,0),(-1,-1),5*mm),("RIGHTPADDING",(0,0),(-1,-1),5*mm),
        ("TOPPADDING",(0,0),(-1,-1),4*mm),("BOTTOMPADDING",(0,0),(-1,-1),4*mm)
    ]))
    story.append(Spacer(1,5*mm))

    story.append(Paragraph("Comparaison des solutions",H2))
    scenarios=[("Double",double_cost),("VARIO",vario_cost),("VARIO + batterie PV",vario_pv_bill)]
    if arbitrage_enabled and vario_grid_bill is not None:
        scenarios.append(("VARIO + arbitrage",vario_grid_bill))
    story.append(_scenario_bars(scenarios))
    story.append(Spacer(1,5*mm))

    story.append(Paragraph("D'ou viennent les economies ?",H2))
    steps=[
        ["Etape","Effet sur la facture","Lecture"],
        ["1. Double -> VARIO",_money(gain_vario),"Effet du changement de tarif seul."],
        ["2. Stockage du surplus PV",_money(gain_pv),"Le surplus solaire est conserve puis utilise plus tard."],
    ]
    if arbitrage_enabled:
        steps.append(["3. Arbitrage reseau VARIO",_money(gain_arb),"Charge quand VARIO est bas, decharge quand il est haut."])
    tab=Table(steps,colWidths=[55*mm,35*mm,90*mm],repeatRows=1)
    tab.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),DARK),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(0,1),(-1,-1),"Helvetica"),
        ("FONTSIZE",(0,0),(-1,-1),8),("GRID",(0,0),(-1,-1),0.5,HexColor("#d1d5db")),
        ("VALIGN",(0,0),(-1,-1),"TOP"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,LIGHT]),
        ("LEFTPADDING",(0,0),(-1,-1),3*mm),("RIGHTPADDING",(0,0),(-1,-1),3*mm),
        ("TOPPADDING",(0,0),(-1,-1),2.5*mm),("BOTTOMPADDING",(0,0),(-1,-1),2.5*mm),
    ]))
    story.append(tab)

    story.append(PageBreak())
    story.append(Paragraph("Evolution mensuelle",H2))
    chart_cols=["double","vario","vario_pv"]
    chart_labels=["Double","VARIO","VARIO + batt. PV"]
    if arbitrage_enabled and monthly_df is not None and "vario_grid" in monthly_df.columns:
        chart_cols.append("vario_grid"); chart_labels.append("VARIO + arbitrage")
    chart=_monthly_chart(monthly_df,chart_cols,chart_labels)
    if chart:
        story.append(chart)
    story.append(Spacer(1,4*mm))

    story.append(Paragraph("Hypotheses de simulation",H2))
    hypotheses=[
        ["Batterie",f"{capacity_kwh:.1f} kWh / {power_kw:.1f} kW"],
        ["Rendement aller-retour",f"{efficiency*100:.0f} %"],
        ["Plage SOC",f"{soc_min:.0f} % - {soc_max:.0f} %"],
        ["Reprise PV",f"{feed_in_ct:.1f} ct/kWh"],
        ["Cout d'usure retenu",f"{wear_ct:.1f} ct/kWh decharge"],
        ["Arbitrage reseau","Oui" if arbitrage_enabled else "Non"],
    ]
    htab=Table(hypotheses,colWidths=[75*mm,105*mm])
    htab.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.5,HexColor("#d1d5db")),
        ("BACKGROUND",(0,0),(0,-1),LIGHT),
        ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),
        ("FONTNAME",(1,0),(1,-1),"Helvetica"),
        ("FONTSIZE",(0,0),(-1,-1),8.5),
        ("LEFTPADDING",(0,0),(-1,-1),3*mm),("RIGHTPADDING",(0,0),(-1,-1),3*mm),
        ("TOPPADDING",(0,0),(-1,-1),2.5*mm),("BOTTOMPADDING",(0,0),(-1,-1),2.5*mm),
    ]))
    story.append(htab)
    story.append(Spacer(1,4*mm))

    notes = [
        "Les frais fixes identiques aux deux tarifs ne sont pas inclus dans la comparaison.",
        "Le gain net apres usure est un indicateur economique interne base sur l'hypothese de cout d'usure choisie.",
        "La projection annuelle est une annualisation de la periode observee et devient plus fiable a mesure que l'historique VARIO s'allonge.",
        "Le pilotage presente est un backtest historique optimal : en exploitation reelle, seules les informations tarifaires publiees a l'avance peuvent etre utilisees."
    ]
    if profile_transposed:
        notes.insert(0,"Le profil de charge mesure en 2025 a ete transpose sur 2026. Il ne s'agit pas de mesures reelles 2026.")
    story.append(Paragraph("Remarques",H2))
    for n in notes:
        story.append(Paragraph("• "+n,SMALL))
        story.append(Spacer(1,1*mm))

    doc.build(story)
    return bio.getvalue()
