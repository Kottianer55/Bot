import os
import time
import logging
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime

# Aktiviert ANSI-Farben auch in der klassischen Windows-Eingabeaufforderung (CMD)
os.system("")

# --- TERMINAL FARBEN (ANSI CODES - FETT & LEUCHTEND) ---
FARBE_GRUEN = "\033[1;92m"  # Leuchtend Grün & Fett (Steigend / LONG)
FARBE_ROT = "\033[1;91m"    # Leuchtend Rot & Fett (Fallend / SHORT)
FARBE_GELB = "\033[1;93m"   # Leuchtend Gelb & Fett (Warnung / Info)
FARBE_RESET = "\033[0m"

# --- KONFIGURATION ---
TELEGRAM_TOKEN = "9290550997:AAGxSfWwmTTXKrwiKgdBfL6jJK37MjOVhTk"
CHAT_ID ="6637031003"
MAX_SLIPPAGE_PROZENT = 1.5

SYMBOLE = {
    "Gold (USD)": {
        "symbol": "GOLD",
        "yf_symbol": "GC=F",
        "volume": 0.006,
        "atr_sl_mult": 1.5,
        "atr_tp_mult": 3.0,
    },
    "EUR/USD": {
        "symbol": "EURUSD",
        "yf_symbol": "EURUSD=X",
        "volume": 0.05,
        "atr_sl_mult": 1.5,
        "atr_tp_mult": 3.0,
    },
    "OIL": {
        "symbol": "OIL",
        "yf_symbol": "CL=F",
        "volume": 0.01,
        "atr_sl_mult": 2.0,
        "atr_tp_mult": 4.0,
    },
    "US100": {
        "symbol": "US100",
        "yf_symbol": "NQ=F",
        "volume": 0.01,
        "atr_sl_mult": 1.5,
        "atr_tp_mult": 3.0,
    },
    "Bitcoin": {
        "symbol": "BTC",
        "yf_symbol": "BTC-USD",
        "volume": 0.001,
        "atr_sl_mult": 2.0,
        "atr_tp_mult": 4.0,
    }
}

aktive_positionen = {}
geschlossene_trades_heute = []
letztes_zusammenfassungs_datum = ""


def schreibe_log(nachricht, typ="normal"):
    zeitstempel = time.strftime("%Y-%m-%d %H:%M:%S")
    if typ == "long":
        print(f"{FARBE_GRUEN}[{zeitstempel}] 🟢 {nachricht}{FARBE_RESET}")
    elif typ == "short":
        print(f"{FARBE_ROT}[{zeitstempel}] 🔴 {nachricht}{FARBE_RESET}")
    elif typ == "warnung":
        print(f"{FARBE_GELB}[{zeitstempel}] ⚠️ {nachricht}{FARBE_RESET}")
    else:
        print(f"[{zeitstempel}] {nachricht}")


def sende_telegram_nachricht(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }

    for versuch in range(3):
        try:
            response = requests.post(url, data=payload, timeout=10)
            if response.status_code == 200:
                return
            else:
                schreibe_log(f"Telegram API Statuscode {response.status_code}", "warnung")
        except Exception as e:
            if versuch == 2:
                schreibe_log(f"Telegram-Fehler nach 3 Versuchen: {e}", "warnung")
            time.sleep(2)


def hole_daten(yf_symbol, intervall="1h"):
    try:
        df = yf.download(yf_symbol, period="60d", interval=intervall, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        schreibe_log(f"Fehler beim Datenabruf ({intervall}) für {yf_symbol}: {e}", "warnung")
        return None


def hole_aktuellen_preis(yf_symbol):
    try:
        t = yf.Ticker(yf_symbol)
        history = t.history(period="1d", interval="1m")
        if not history.empty:
            return float(history["Close"].iloc[-1])
        return None
    except Exception as e:
        schreibe_log(f"Fehler beim Live-Preis für {yf_symbol}: {e}", "warnung")
        return None


def berechne_rsi(df, window=14):
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def berechne_atr(df, window=14):
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift()).abs()
    low_close = (df['Low'] - df['Close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    atr = true_range.rolling(window=window).mean()
    return atr


def berechne_macd(df, fast=12, slow=26, signal=9):
    exp1 = df['Close'].ewm(span=fast, adjust=False).mean()
    exp2 = df['Close'].ewm(span=slow, adjust=False).mean()
    macd = exp1 - exp2
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    histogram = macd - signal_line
    return macd, signal_line, histogram


def ist_handelszeit():
    # 24/7 Modus für alle Assets aktiv (0:00 bis 0:00 Uhr)
    return True


def sende_taeglichen_report_wenn_faellig():
    global letztes_zusammenfassungs_datum, geschlossene_trades_heute
    jetzt = datetime.now()
    heutiges_datum = jetzt.strftime("%Y-%m-%d")

    if jetzt.hour >= 22 and letztes_zusammenfassungs_datum != heutiges_datum:
        anzahl_trades = len(geschlossene_trades_heute)

        if anzahl_trades > 0:
            gesamt_pnl = sum([t['pnl'] for t in geschlossene_trades_heute])
            gewinner = len([t for t in geschlossene_trades_heute if t['pnl'] > 0])
            verlierer = len([t for t in geschlossene_trades_heute if t['pnl'] <= 0])
            win_rate = (gewinner / anzahl_trades) * 100

            status_emoji = "🟢" if gesamt_pnl >= 0 else "🔴"

            report_text = (
                f"📊 <b>EUROBORSA TÄGLICHER PERFORMANCE-REPORT</b>\n"
                f"📅 <b>Datum:</b> {heutiges_datum}\n\n"
                f"📈 <b>Gesamt-Trades:</b> {anzahl_trades}\n"
                f"🏆 <b>Gewinner / Verlierer:</b> {gewinner} / {verlierer} (Win-Rate: {win_rate:.1f}%)\n"
                f"💰 <b>Gesamt-Ergebnis (PnL):</b> {status_emoji} <code>{gesamt_pnl:+.2f}%</code>\n\n"
                f"--- <b>Trade-Details:</b> ---\n"
            )

            for t in geschlossene_trades_heute:
                pnl_symbol = "🟢" if t['pnl'] > 0 else "🔴"
                report_text += f"{pnl_symbol} {t['asset']} ({t['richtung']}): <code>{t['pnl']:+.2f}%</code> ({t['grund']})\n"
        else:
            report_text = (
                f"📊 <b>EUROBORSA TÄGLICHER PERFORMANCE-REPORT</b>\n"
                f"📅 <b>Datum:</b> {heutiges_datum}\n\n"
                f"ℹ️ Heute wurden keine Trades ausgeführt oder geschlossen."
            )

        sende_telegram_nachricht(report_text)
        schreibe_log("Täglicher Performance-Report wurde via Telegram gesendet.")
        letztes_zusammenfassungs_datum = heutiges_datum
        geschlossene_trades_heute = []


def verwalte_trailing_stop(symbol_key, aktueller_preis):
    if symbol_key in aktive_positionen:
        pos = aktive_positionen[symbol_key]
        if pos['richtung'] == 'LONG':
            if aktueller_preis > pos['hoechstpreis']:
                pos['hoechstpreis'] = aktueller_preis
                neuer_sl = pos['hoechstpreis'] - pos['atr_wert']
                if neuer_sl > pos['sl']:
                    pos['sl'] = neuer_sl
                    schreibe_log(f"Trailing Stop (LONG) aktualisiert für {symbol_key} bei {pos['sl']:.4f}", "long")
                    sende_telegram_nachricht(
                        f"🛡️ <b>TRAILING STOP (LONG)</b> für {symbol_key}\nNeuer SL: <code>{pos['sl']:.4f}</code>")
        elif pos['richtung'] == 'SHORT':
            if aktueller_preis < pos['tiefstpreis']:
                pos['tiefstpreis'] = aktueller_preis
                neuer_sl = pos['tiefstpreis'] + pos['atr_wert']
                if neuer_sl < pos['sl']:
                    pos['sl'] = neuer_sl
                    schreibe_log(f"Trailing Stop (SHORT) aktualisiert für {symbol_key} bei {pos['sl']:.4f}", "short")
                    sende_telegram_nachricht(
                        f"🛡️ <b>TRAILING STOP (SHORT)</b> für {symbol_key}\nNeuer SL: <code>{pos['sl']:.4f}</code>")


def pruefe_position_exit(symbol_key, aktueller_preis, asset_name):
    if symbol_key in aktive_positionen:
        pos = aktive_positionen[symbol_key]
        richtung = pos['richtung']
        sl = pos['sl']
        tp = pos['tp']
        tp_halb = pos['tp_halb']

        if not pos['teil_tp_erreicht']:
            if richtung == 'LONG' and aktueller_preis >= tp_halb:
                pos['teil_tp_erreicht'] = True
                pos['sl'] = pos['entry']
                teil_pnl = ((aktueller_preis - pos['entry']) / pos['entry']) * 100
                schreibe_log(
                    f"TEILGEWINN (LONG) erreicht für {asset_name} bei {aktueller_preis:.2f}! SL auf Break-Even gesetzt.",
                    "long")
                sende_telegram_nachricht(
                    f"🎯 <b>TEILGEWINNMITNAHME (LONG)</b>\n\n"
                    f"<b>Asset:</b> {asset_name}\n"
                    f"<b>Kurs:</b> <code>{aktueller_preis:.2f}</code> (Teil-PnL: +{teil_pnl:.2f}%)\n"
                    f"🛡️ <i>Stop-Loss wurde automatisch auf Einstand ({pos['entry']:.2f}) gezogen! Rest läuft zum TP.</i>"
                )
            elif richtung == 'SHORT' and aktueller_preis <= tp_halb:
                pos['teil_tp_erreicht'] = True
                pos['sl'] = pos['entry']
                teil_pnl = ((pos['entry'] - aktueller_preis) / pos['entry']) * 100
                schreibe_log(
                    f"TEILGEWINN (SHORT) erreicht für {asset_name} bei {aktueller_preis:.2f}! SL auf Break-Even gesetzt.",
                    "short")
                sende_telegram_nachricht(
                    f"🎯 <b>TEILGEWINNMITNAHME (SHORT)</b>\n\n"
                    f"<b>Asset:</b> {asset_name}\n"
                    f"<b>Kurs:</b> <code>{aktueller_preis:.2f}</code> (Teil-PnL: +{teil_pnl:.2f}%)\n"
                    f"🛡️ <i>Stop-Loss wurde automatisch auf Einstand ({pos['entry']:.2f}) gezogen! Rest läuft zum TP.</i>"
                )

        erfolgt_exit = False
        grund = ""
        log_typ = "normal"

        if richtung == 'LONG':
            if aktueller_preis <= sl:
                erfolgt_exit = True
                grund = "Stop-Loss / Break-Even (SL)"
                log_typ = "short"
            elif aktueller_preis >= tp:
                erfolgt_exit = True
                grund = "Take-Profit (TP)"
                log_typ = "long"
        elif richtung == 'SHORT':
            if aktueller_preis >= sl:
                erfolgt_exit = True
                grund = "Stop-Loss / Break-Even (SL)"
                log_typ = "short"
            elif aktueller_preis <= tp:
                erfolgt_exit = True
                grund = "Take-Profit (TP)"
                log_typ = "long"

        if erfolgt_exit:
            if richtung == 'LONG':
                pnl_prozent = ((aktueller_preis - pos['entry']) / pos['entry']) * 100
            else:
                pnl_prozent = ((pos['entry'] - aktueller_preis) / pos['entry']) * 100

            ergebnis_text = "GEWINN 🟢" if pnl_prozent > 0 else "VERLUST 🔴"

            exit_log_msg = f"POSITION GESCHLOSSEN ({richtung}) für {asset_name} wegen {grund} | Exit: {aktueller_preis:.2f} | PnL: {pnl_prozent:+.2f}%"
            schreibe_log(exit_log_msg, log_typ)

            geschlossene_trades_heute.append({
                'asset': asset_name,
                'richtung': richtung,
                'entry': pos['entry'],
                'exit': aktueller_preis,
                'pnl': pnl_prozent,
                'grund': grund
            })

            exit_telegram_text = (
                f"🚨 <b>EUROBORSA POSITION GESCHLOSSEN</b>\n\n"
                f"<b>Asset:</b> {asset_name}\n"
                f"<b>Richtung:</b> {richtung}\n"
                f"<b>Status:</b> {ergebnis_text}\n"
                f"<b>Grund:</b> {grund} erreicht\n\n"
                f"🔹 <b>Einstiegskurs:</b> <code>{pos['entry']:.2f}</code>\n"
                f"🔸 <b>Exit-Preis:</b> <code>{aktueller_preis:.2f}</code>\n"
                f"📊 <b>Ergebnis (PnL):</b> <code>{pnl_prozent:+.2f}%</code>"
            )
            sende_telegram_nachricht(exit_telegram_text)
            del aktive_positionen[symbol_key]
            return True
    return False


def analysiere_markt(asset_name, config):
    yf_symbol = config["yf_symbol"]
    symbol_key = config["symbol"]

    live_preis = hole_aktuellen_preis(yf_symbol)
    if live_preis is not None:
        if pruefe_position_exit(symbol_key, live_preis, asset_name):
            return

    df_1h = hole_daten(yf_symbol, intervall="1h")
    df_4h = hole_daten(yf_symbol, intervall="4h")

    if df_1h is None or len(df_1h) < 200 or df_4h is None or len(df_4h) < 50:
        schreibe_log(f"Nicht genügend Daten (1H/4H) für {asset_name} verfügbar.", "warnung")
        return

    df_4h["SMA_50_4H"] = df_4h["Close"].rolling(window=50).mean()
    preis_4h = df_4h["Close"].iloc[-1]
    sma_4h = df_4h["SMA_50_4H"].iloc[-1]
    trend_4h_long = preis_4h > sma_4h
    trend_4h_short = preis_4h < sma_4h

    df_1h["SMA_20"] = df_1h["Close"].rolling(window=20).mean()
    df_1h["RSI"] = berechne_rsi(df_1h)
    df_1h["ATR"] = berechne_atr(df_1h)
    macd, signal_line, histogram = berechne_macd(df_1h)
    df_1h["MACD"] = macd
    df_1h["MACD_Signal"] = signal_line

    analysierter_preis = df_1h["Close"].iloc[-1]
    letzter_sma = df_1h["SMA_20"].iloc[-1]
    aktueller_rsi = df_1h["RSI"].iloc[-1]
    aktueller_atr = df_1h["ATR"].iloc[-1]

    if live_preis is not None:
        slippage_abweichung = abs(live_preis - analysierter_preis) / analysierter_preis * 100
        schreibe_log(
            f"--- Analyse {asset_name} [1H/4H] --- Live: {live_preis:.4f} | 4H-Trend: {'BULLISCH' if trend_4h_long else 'BÄRISCH'} | RSI: {aktueller_rsi:.1f}"
        )

        if slippage_abweichung > MAX_SLIPPAGE_PROZENT:
            schreibe_log(f"[SCHUTZ-STOP] Abweichung zu hoch ({slippage_abweichung:.3f}%).", "warnung")
            return

        ausfuehrungs_preis = live_preis
    else:
        ausfuehrungs_preis = analysierter_preis

    verwalte_trailing_stop(symbol_key, ausfuehrungs_preis)

    if symbol_key in aktive_positionen:
        pos = aktive_positionen[symbol_key]
        status_typ = "long" if pos['richtung'] == 'LONG' else "short"
        schreibe_log(
            f"Position für {asset_name} ({pos['richtung']}) läuft bereits | Einstieg: {pos['entry']:.2f} | SL: {pos['sl']:.2f} | TP: {pos['tp']:.2f}",
            status_typ)
        return

    if not ist_handelszeit():
        schreibe_log(f"Ausserhalb der Handelszeiten für {asset_name}. Keine neuen Trades.")
        return

    erfülle_long = trend_4h_long and analysierter_preis > letzter_sma and aktueller_rsi < 75
    erfülle_short = trend_4h_short and analysierter_preis < letzter_sma and aktueller_rsi > 25

    # --- STEIGEND KAUFEN (LONG - GRÜN IM TERMINAL) ---
    if erfülle_long:
        sl_wert = aktueller_atr * config["atr_sl_mult"]
        tp_wert = aktueller_atr * config["atr_tp_mult"]
        sl = ausfuehrungs_preis - sl_wert
        tp = ausfuehrungs_preis + tp_wert
        tp_halb = ausfuehrungs_preis + (tp_wert / 2)

        schreibe_log("=" * 68, "long")
        schreibe_log(f"KAUF-SIGNAL (STEIGEND / LONG) >>> {asset_name} ({symbol_key})", "long")
        schreibe_log(
            f"Einstieg: {ausfuehrungs_preis:.2f} | SL: {sl:.2f} | Teil-TP1: {tp_halb:.2f} | Gesamt-TP: {tp:.2f}",
            "long")
        schreibe_log("=" * 68, "long")

        signal_text = (
            f"🚀 <b>EUROBORSA MULTI-TIMEFRAME SIGNAL</b>\n\n"
            f"<b>Asset:</b> {asset_name}\n"
            f"<b>Richtung:</b> 🟢 <b>LONG (KAUF)</b>\n"
            f"<b>4H-Trend:</b> BULLISCH 📈 | <b>1H-RSI:</b> {aktueller_rsi:.1f}\n"
            f"<b>ATR (Volatilität):</b> <code>{aktueller_atr:.2f}</code>\n\n"
            f"🔹 <b>Einstiegskurs:</b> <code>{ausfuehrungs_preis:.2f}</code>\n"
            f"🛑 <b>Stop-Loss (ATR):</b> <code>{sl:.2f}</code>\n"
            f"🎯 <b>Teilgewinn (TP1):</b> <code>{tp_halb:.2f}</code>\n"
            f"🎯 <b>Take-Profit (Gesamt):</b> <code>{tp:.2f}</code>"
        )
        sende_telegram_nachricht(signal_text)
        aktive_positionen[symbol_key] = {
            'richtung': 'LONG',
            'entry': ausfuehrungs_preis,
            'sl': sl,
            'tp': tp,
            'tp_halb': tp_halb,
            'teil_tp_erreicht': False,
            'hoechstpreis': ausfuehrungs_preis,
            'atr_wert': sl_wert
        }

    # --- FALLEND KAUFEN / VERKAUFEN (SHORT - ROT IM TERMINAL) ---
    elif erfülle_short:
        sl_wert = aktueller_atr * config["atr_sl_mult"]
        tp_wert = aktueller_atr * config["atr_tp_mult"]
        sl = ausfuehrungs_preis + sl_wert
        tp = ausfuehrungs_preis - tp_wert
        tp_halb = ausfuehrungs_preis - (tp_wert / 2)

        schreibe_log("=" * 68, "short")
        schreibe_log(f"VERKAUFS-SIGNAL (FALLEND / SHORT) >>> {asset_name} ({symbol_key})", "short")
        schreibe_log(
            f"Einstieg: {ausfuehrungs_preis:.2f} | SL: {sl:.2f} | Teil-TP1: {tp_halb:.2f} | Gesamt-TP: {tp:.2f}",
            "short")
        schreibe_log("=" * 68, "short")

        signal_text = (
            f"📉 <b>EUROBORSA MULTI-TIMEFRAME SIGNAL</b>\n\n"
            f"<b>Asset:</b> {asset_name}\n"
            f"<b>Richtung:</b> 🔴 <b>SHORT (VERKAUF)</b>\n"
            f"<b>4H-Trend:</b> BÄRISCH 📉 | <b>1H-RSI:</b> {aktueller_rsi:.1f}\n"
            f"<b>ATR (Volatilität):</b> <code>{aktueller_atr:.2f}</code>\n\n"
            f"🔹 <b>Einstiegskurs:</b> <code>{ausfuehrungs_preis:.2f}</code>\n"
            f"🛑 <b>Stop-Loss (ATR):</b> <code>{sl:.2f}</code>\n"
            f"🎯 <b>Teilgewinn (TP1):</b> <code>{tp_halb:.2f}</code>\n"
            f"🎯 <b>Take-Profit (Gesamt):</b> <code>{tp:.2f}</code>"
        )
        sende_telegram_nachricht(signal_text)
        aktive_positionen[symbol_key] = {
            'richtung': 'SHORT',
            'entry': ausfuehrungs_preis,
            'sl': sl,
            'tp': tp,
            'tp_halb': tp_halb,
            'teil_tp_erreicht': False,
            'tiefstpreis': ausfuehrungs_preis,
            'atr_wert': sl_wert
        }


def main():
    sende_telegram_nachricht("🚀 Euroborsa Multi-Timeframe Bot (24/7 Modus) gestartet!")
    schreibe_log("Bot im 24/7-Modus (rund um die Uhr) gestartet. Überwache Märkte...")

    while True:
        sende_taeglichen_report_wenn_faellig()

        for asset_name, config in SYMBOLE.items():
            try:
                analysiere_markt(asset_name, config)
            except Exception as e:
                schreibe_log(f"Fehler bei der Analyse von {asset_name}: {e}", "warnung")

        schreibe_log("Zyklus beendet. Warte 60 Sekunden bis zum nächsten Check...")
        time.sleep(60)


if __name__ == "__main__":
    main()