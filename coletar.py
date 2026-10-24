"""Coletor do Painel Sobé.

Lê (somente leitura) os dados já publicados de cada dash em clientes.json e o
status da última GitHub Action de cada repo, e grava status.json — um resumo
pequeno e no mesmo formato para todos os clientes: série diária de
investimento e conversões por plataforma (Meta, Google, LinkedIn, TikTok) e,
quando o dash tem Hotmart, vendas e faturamento por dia. Não altera nada nos
repos dos clientes.

Uso:  python3 coletar.py            (GITHUB_TOKEN opcional, evita limite da API)
"""
import json
import os
import re
import ssl
import sys
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

PAGES = "https://mggastal.github.io"
DONO = "mggastal"
DIAS_SERIE = 120          # dias diários guardados por cliente
MESES = 12
BRT = timezone(timedelta(hours=-3))
VENDAS = "_vendas"        # pseudo-plataforma: [qtd, valor] por dia

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    CTX = ssl.create_default_context()


def baixar(url, api=False):
    h = {"User-Agent": "sobe-painel"}
    if api:
        h["Accept"] = "application/vnd.github+json"
        if os.environ.get("GITHUB_TOKEN"):
            h["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=90, context=CTX) as r:
        return r.read().decode("utf-8")


def num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def iso(d, ref):
    """'23/10/2026', '23/10/26', '23/10' ou '2026-10-23' -> '2026-10-23'.
    Sem ano: o ano de ref, ou o anterior se a data cair depois de ref."""
    d = str(d).strip()[:10]
    if "-" in d:
        return d
    p = d.split("/")
    dd, mm = int(p[0]), int(p[1])
    if len(p) > 2 and p[2]:
        aa = int(p[2]) + (2000 if len(p[2]) == 2 else 0)
    else:
        aa = ref.year - (1 if (mm, dd) > (ref.month, ref.day) else 0)
    return f"{aa:04d}-{mm:02d}-{dd:02d}"


def novo_acc():
    # por dia: [investimento, conversões, impressões, cliques]
    return defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]))


def somar_serie(acc, plat, dias, *cols, ref):
    for i, dia in enumerate(dias or []):
        s = acc[plat][iso(dia, ref)]
        for k, col in enumerate(cols):
            s[k] += num(col[i]) if col and i < len(col) else 0


def somar_linha(acc, plat, dia, ref, *vals):
    s = acc[plat][iso(dia, ref)]
    for k, v in enumerate(vals):
        s[k] += num(v)


# ---------- leitores: preenchem acc[plataforma][dia] = [spend, conv] ----------

def ler_template(d, acc, ref):
    """Formato dos dashs Sobé (data.json ou consts dentro do HTML)."""
    md = d.get("META_DAILY") or {}
    m = md.get("all") or md.get("lct") or {}
    somar_serie(acc, "meta", m.get("days"), m.get("spend"), m.get("leads"), m.get("impressions"),
                m.get("link_clicks") or m.get("clicks"), ref=ref)
    g = d.get("GOOGLE_DAILY") or {}
    if d.get("USAR_GOOGLE") is not False:
        clk, imp = g.get("clicks"), g.get("impressions")
        if not clk and g.get("cpc"):
            # o template só guarda CTR e CPC do Google: cliques = gasto/CPC, impressões = cliques/CTR
            clk = [num(sp) / num(c) if num(c) else 0 for sp, c in zip(g.get("spend") or [], g["cpc"])]
            imp = [k / (num(t) / 100) if num(t) else 0 for k, t in zip(clk, g.get("ctr") or [])]
        somar_serie(acc, "google", g.get("days"), g.get("spend"), g.get("conversions"), imp, clk, ref=ref)
    li = d.get("LI_DAILY") or {}
    somar_serie(acc, "linkedin", li.get("days"), li.get("spend"), li.get("leads"), li.get("impressions"),
                li.get("clicks"), ref=ref)
    if d.get("USAR_LINKEDIN"):
        for r in d.get("LINKEDIN_RAW") or []:
            somar_linha(acc, "linkedin", r["d"], ref, r.get("sp"), r.get("ld"), r.get("imp"), r.get("cl"))
    tk = d.get("TIKTOK_DAILY") or d.get("TT_DAILY") or {}
    somar_serie(acc, "tiktok", tk.get("days"), tk.get("spend"), tk.get("conversions") or tk.get("leads"),
                tk.get("impressions"), tk.get("clicks"), ref=ref)
    # vendas reais (Hotmart/Eduzz) quando o dash tem: [qtd, valor]
    hd = d.get("HOT_DAILY") or {}
    somar_serie(acc, VENDAS, hd.get("days"), hd.get("qtd"), hd.get("valor"), ref=ref)
    hm = d.get("HOTMART")
    if isinstance(hm, dict) and isinstance(hm.get("daily"), dict):      # gerador_perpetuo
        somar_serie(acc, VENDAS, hm["daily"].get("days"), hm["daily"].get("vendas"), hm["daily"].get("receita"), ref=ref)
    if isinstance(hm, dict) and isinstance(hm.get("diario"), dict):
        dias = hm["diario"].get("dias") or []
        for prod in (hm["diario"].get("prod") or {}).values():
            somar_serie(acc, VENDAS, dias, prod.get("vendas"), prod.get("liq"), ref=ref)


def ler_unibrasil(d, acc, ref):
    for r in d.get("meta") or []:
        somar_linha(acc, "meta", r["d"], ref, r.get("sp"), r.get("ld"), r.get("im"), r.get("ck"))
    for r in d.get("google") or []:
        somar_linha(acc, "google", r["d"], ref, r.get("sp"), r.get("cv"), r.get("im"), r.get("ck"))


def extrair_const(html, nome):
    m = re.search(r"const\s+" + nome + r"\s*=\s*", html)
    if not m:
        return None
    try:
        return json.JSONDecoder().raw_decode(html, m.end())[0]
    except ValueError:
        return None


CONSTS = ("META_DAILY", "GOOGLE_DAILY", "USAR_GOOGLE", "LI_DAILY", "USAR_LINKEDIN", "LINKEDIN_RAW",
          "TIKTOK_DAILY", "TT_DAILY", "HOT_DAILY", "HOTMART", "DATA_GERACAO", "MOEDA_SIMBOLO", "MOEDA_COD",
          "MOEDA", "LANCAMENTO_COD")


def moeda_cod(cod=None, simbolo=None):
    """Código ISO da moeda do dash (padrão BRL)."""
    if cod:
        return str(cod).upper()
    sim = str(simbolo or "").strip()
    return {"$": "USD", "US$": "USD", "U$": "USD", "€": "EUR"}.get(sim, "BRL")


def ref_de(gerado):
    try:
        return date.fromisoformat(iso(gerado, datetime.now(BRT).date()))
    except Exception:
        return datetime.now(BRT).date()


def ler_fonte(repo, fmt, pagina, acc):
    """Lê um repo e soma em acc. Devolve info (gerado, moeda, lançamento)."""
    info = {}
    if fmt == "embed":
        html = baixar(f"{PAGES}/{repo}/{pagina or ''}")
        d = {k: extrair_const(html, k) for k in CONSTS}
        info = {"gerado": d.get("DATA_GERACAO"), "lancamento": d.get("LANCAMENTO_COD"),
                "moeda_cod": moeda_cod(d.get("MOEDA_COD"), d.get("MOEDA_SIMBOLO") or d.get("MOEDA"))}
        ler_template(d, acc, ref_de(info["gerado"]))
        return info
    d = json.loads(baixar(f"{PAGES}/{repo}/data.json"))
    if fmt == "unibrasil":
        info = {"gerado": d.get("gerado_em")}
        ler_unibrasil(d, acc, ref_de(info["gerado"]))
    elif fmt == "cidades":
        cid = d.get((d.get("_META") or {}).get("cidade_padrao")) or {}
        info = {"gerado": cid.get("DATA_GERACAO"), "moeda_cod": moeda_cod(cid.get("MOEDA_COD"), cid.get("MOEDA_SIMBOLO"))}
        for chave in (d.get("_META") or {}).get("cidades", {}):
            if chave in d:
                ler_template(d[chave], acc, ref_de(info["gerado"]))
    elif fmt == "resumo":
        # só o acumulado do lançamento (sem série diária)
        info = {"gerado": d.get("atualizado"), "lancamento": d.get("lancamento"), "kpis": d.get("kpis")}
    else:
        info = {"gerado": d.get("DATA_GERACAO"), "lancamento": d.get("LANCAMENTO_COD"),
                "moeda_cod": moeda_cod(d.get("MOEDA_COD"), d.get("MOEDA_SIMBOLO"))}
        ler_template(d, acc, ref_de(info["gerado"]))
    return info


# ---------- montagem ----------

def resumir(acc):
    plats = sorted(p for p in acc if p != VENDAS and any(v[0] for v in acc[p].values()))
    dias = sorted({dia for p in plats + ([VENDAS] if VENDAS in acc else []) for dia in acc[p]})
    if not dias:
        return {}
    ult_inv = max((dia for p in plats for dia, v in acc[p].items() if v[0] > 0), default=None)
    # a janela termina hoje (BRT) para todos: conta parada aparece com zeros
    fim = max(date.fromisoformat(dias[-1]), datetime.now(BRT).date())
    janela = [(fim - timedelta(days=i)).isoformat() for i in range(DIAS_SERIE - 1, -1, -1)]
    serie = {"dias": janela}
    chaves = plats + ([VENDAS] if VENDAS in acc else [])
    for p in chaves:
        n = 2 if p == VENDAS else 4
        serie[p] = [[round(v, 2) for v in acc[p][dia][:n]] if dia in acc[p] else [0] * n for dia in janela]
    meses = defaultdict(lambda: [0.0, 0.0])
    por_plat = defaultdict(lambda: defaultdict(float))
    for p in plats:
        for dia, (sp, cv, *_) in acc[p].items():
            meses[dia[:7]][0] += sp
            meses[dia[:7]][1] += cv
            por_plat[p][dia[:7]] += sp
    ult_meses = sorted(meses)[-MESES:]
    return {
        "ultimo_dia": ult_inv,
        "plataformas": plats,
        "tem_vendas": VENDAS in acc and any(v[0] for v in acc[VENDAS].values()),
        "serie": serie,
        "meses": [[m, round(meses[m][0], 2), round(meses[m][1], 1)] for m in ult_meses],
        "meses_plat": {p: {m: round(por_plat[p][m], 2) for m in ult_meses if por_plat[p][m]} for p in plats},
    }


def workflow(repo):
    try:
        runs = json.loads(baixar(f"https://api.github.com/repos/{DONO}/{repo}/actions/runs?per_page=10", api=True))
    except Exception as e:
        return {"erro": str(e)[:120]}
    for r in runs.get("workflow_runs") or []:
        if r.get("event") == "dynamic":      # deploy do Pages, não é o gerador
            continue
        return {"conclusao": r.get("conclusion"), "status": r.get("status"), "quando": r.get("updated_at")}
    return None


def coletar(c):
    fontes = [(c["repo"], c.get("formato", "template"), c.get("pagina"))]
    fontes += [(s["repo"], s.get("formato", c.get("formato")), s.get("pagina")) for s in c.get("somar") or []]
    acc, out, erros, wfs = novo_acc(), {"formato": c.get("formato")}, [], []
    for repo, fmt, pagina in fontes:
        try:
            info = ler_fonte(repo, fmt, pagina, acc)
            for k, v in info.items():
                if v and k not in out:
                    out[k] = v
        except Exception as e:
            erros.append(f"{repo}: {type(e).__name__}: {str(e)[:120]}")
        wfs.append(workflow(repo) or {})
    out.update(resumir(acc))
    # moeda por plataforma: o cadastro manda (ex.: Adopt Google em USD), senão a moeda do dash
    padrao = out.pop("moeda_cod", None) or "BRL"
    out["moedas"] = {p: (c.get("moedas") or {}).get(p) or padrao for p in out.get("plataformas", [])}
    out["moeda_vendas"] = (c.get("moedas") or {}).get("vendas") or padrao
    out["ok"] = not erros
    if erros:
        out["erro"] = " | ".join(erros)
    # saúde: a pior execução entre os repos somados
    falhas = [w for w in wfs if w.get("conclusao") == "failure"]
    datas = [w["quando"] for w in wfs if w.get("quando")]
    out["workflow"] = {"conclusao": "failure" if falhas else (wfs[0].get("conclusao") if wfs else None),
                       "quando": min(datas) if datas else None}
    return out


def cambio():
    """Cotação diária (compra) em R$ das moedas estrangeiras, para os totais convertidos."""
    out = {}
    for m in ("USD", "EUR"):
        try:
            lst = json.loads(baixar(f"https://economia.awesomeapi.com.br/json/daily/{m}-BRL/150"))
            out[m] = {datetime.fromtimestamp(int(x["timestamp"]), BRT).date().isoformat(): round(float(x["bid"]), 4)
                      for x in lst}
        except Exception as e:
            print("cotação", m, "falhou:", e)
    return out


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    cad = json.load(open(os.path.join(base, "clientes.json"), encoding="utf-8"))
    res = {}
    for c in cad["clientes"]:
        r = res[c["repo"]] = coletar(c)
        print(f"{c['repo']:<22} {'ok ' if r['ok'] else 'ERRO'} ultimo={r.get('ultimo_dia', '-')} "
              f"plats={','.join(r.get('plataformas', []))} vendas={r.get('tem_vendas', False)} "
              f"wf={r['workflow'].get('conclusao')}", r.get("erro", ""))
    status = {"gerado_em": datetime.now(BRT).isoformat(timespec="seconds"), "cambio": cambio(), "clientes": res}
    with open(os.path.join(base, "status.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, separators=(",", ":"))
    print("status.json:", os.path.getsize(os.path.join(base, "status.json")) // 1024, "KB")


if __name__ == "__main__":
    sys.exit(main())
