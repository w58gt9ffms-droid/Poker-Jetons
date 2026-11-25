#!/usr/bin/env python3
"""Poker Jetons — serveur de jetons virtuels pour jouer au poker avec de vraies cartes.

Aucune dépendance : seulement Python 3 (déjà installé sur macOS).
Lancer :  python3 server.py   puis ouvrir l'adresse affichée.
"""
import json
import os
import secrets
import socket
import string
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else 8000))
BASE = os.path.dirname(os.path.abspath(__file__))
# Les pages peuvent être dans static/ ou directement à côté de server.py
STATIC = os.path.join(BASE, "static") if os.path.isfile(os.path.join(BASE, "static", "table.html")) else BASE
STREETS = ["preflop", "flop", "turn", "river"]
GAME_TTL = 24 * 3600

LOCK = threading.Lock()
GAMES = {}


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # aucun paquet envoyé, sert à trouver l'IP locale
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def new_code():
    alphabet = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if code not in GAMES:
            return code


class GameError(Exception):
    pass


class Game:
    def __init__(self, stack, sb, bb):
        self.code = new_code()
        self.host_token = None
        self.start_stack = stack
        self.sb = sb
        self.bb = bb
        self.players = []  # ordre = ordre autour de la table
        self.pot = 0
        self.street = None
        self.hand_active = False
        self.hand_number = 0
        self.dealer = -1
        self.to_act = None
        self.log = []
        self.version = 0
        self.touched = time.time()

    # ---------- utilitaires ----------
    def add_log(self, msg):
        self.log.append({"t": time.time(), "msg": msg})
        self.log = self.log[-60:]

    def bump(self):
        self.version += 1
        self.touched = time.time()

    def player_by_token(self, token):
        for p in self.players:
            if p["token"] == token:
                return p
        raise GameError("Joueur inconnu — rejoins la partie.")

    def player_by_id(self, pid):
        for p in self.players:
            if p["id"] == pid:
                return p
        raise GameError("Joueur introuvable.")

    def idx(self, p):
        return self.players.index(p)

    def max_bet(self):
        return max([p["street_bet"] for p in self.players] or [0])

    def in_hand(self):
        return [p for p in self.players if p["in_hand"] and not p["folded"]]

    def next_seat(self, start, pred):
        n = len(self.players)
        for k in range(1, n + 1):
            i = (start + k) % n
            if pred(self.players[i]):
                return i
        return None

    def can_act(self, p):
        return p["in_hand"] and not p["folded"] and p["stack"] > 0

    def advance_turn(self, from_idx):
        if not self.hand_active:
            self.to_act = None
            return
        nxt = self.next_seat(from_idx, self.can_act)
        self.to_act = self.players[nxt]["id"] if nxt is not None else None

    # ---------- joueurs ----------
    def join(self, name):
        name = (name or "").strip()[:20]
        if not name:
            raise GameError("Choisis un pseudo.")
        if any(p["name"].lower() == name.lower() for p in self.players):
            raise GameError("Ce pseudo est déjà pris à cette table.")
        if len(self.players) >= 12:
            raise GameError("Table pleine (12 joueurs max).")
        p = {
            "id": secrets.token_hex(4),
            "token": secrets.token_urlsafe(16),
            "name": name,
            "stack": self.start_stack,
            "street_bet": 0,
            "hand_bet": 0,
            "folded": False,
            "in_hand": False,
            "last_seen": time.time(),
        }
        self.players.append(p)
        self.add_log(f"{name} rejoint la table avec {self.start_stack} jetons.")
        return p

    # ---------- actions de jeu ----------
    def put_in(self, p, amount):
        amount = min(amount, p["stack"])
        p["stack"] -= amount
        p["street_bet"] += amount
        p["hand_bet"] += amount
        self.pot += amount
        return amount

    def act(self, p, kind, amount=0):
        if not self.hand_active:
            raise GameError("Aucune main en cours. L'organisateur doit lancer une nouvelle main.")
        if not p["in_hand"]:
            raise GameError("Tu n'es pas dans cette main (tu as rejoint en cours de route).")
        if p["folded"]:
            raise GameError("Tu t'es déjà couché pour cette main.")
        to_call = self.max_bet() - p["street_bet"]

        if kind == "fold":
            p["folded"] = True
            self.add_log(f"{p['name']} se couche.")
            alive = self.in_hand()
            if len(alive) == 1:
                self.add_log(f"Tout le monde s'est couché : {alive[0]['name']} peut remporter le pot.")
        elif kind == "check":
            if to_call > 0:
                raise GameError(f"Impossible de checker : il faut suivre {to_call}.")
            self.add_log(f"{p['name']} checke.")
        elif kind == "call":
            if to_call <= 0:
                raise GameError("Rien à suivre — tu peux checker.")
            put = self.put_in(p, to_call)
            tag = " (tapis)" if p["stack"] == 0 else ""
            self.add_log(f"{p['name']} suit {put}{tag}.")
        elif kind == "bet":
            try:
                amount = int(amount)
            except (TypeError, ValueError):
                raise GameError("Montant invalide.")
            if amount <= 0:
                raise GameError("Le montant doit être positif.")
            if amount > p["stack"]:
                raise GameError(f"Tu n'as que {p['stack']} jetons.")
            if amount < to_call and amount < p["stack"]:
                raise GameError(f"Il faut au moins {to_call} pour suivre.")
            put = self.put_in(p, amount)
            total = p["street_bet"]
            if p["stack"] == 0:
                self.add_log(f"{p['name']} fait tapis : {put} (total {total}).")
            elif to_call == 0:
                self.add_log(f"{p['name']} mise {put}.")
            elif put == to_call:
                self.add_log(f"{p['name']} suit {put}.")
            else:
                self.add_log(f"{p['name']} relance à {total}.")
        elif kind == "allin":
            if p["stack"] <= 0:
                raise GameError("Tu n'as plus de jetons.")
            put = self.put_in(p, p["stack"])
            self.add_log(f"{p['name']} fait tapis : {put} (total {p['street_bet']}).")
        else:
            raise GameError("Action inconnue.")
        self.advance_turn(self.idx(p))

    # ---------- actions organisateur ----------
    def new_hand(self):
        if self.hand_active and self.pot > 0:
            raise GameError("Il reste des jetons dans le pot : désigne d'abord le gagnant.")
        eligible = [p for p in self.players if p["stack"] > 0]
        if len(eligible) < 2:
            raise GameError("Il faut au moins 2 joueurs avec des jetons.")
        for p in self.players:
            p["street_bet"] = 0
            p["hand_bet"] = 0
            p["folded"] = False
            p["in_hand"] = p["stack"] > 0
        self.pot = 0
        self.hand_number += 1
        self.hand_active = True
        self.street = "preflop"
        active = lambda q: q["in_hand"]
        self.dealer = self.next_seat(self.dealer if self.dealer >= 0 else -1, active)
        d = self.players[self.dealer]
        self.add_log(f"— Main n°{self.hand_number} — Donneur : {d['name']}.")
        if self.bb > 0:
            if len(eligible) == 2:
                sb_i = self.dealer
            else:
                sb_i = self.next_seat(self.dealer, active)
            bb_i = self.next_seat(sb_i, active)
            sbp, bbp = self.players[sb_i], self.players[bb_i]
            a = self.put_in(sbp, self.sb)
            b = self.put_in(bbp, self.bb)
            self.add_log(f"Blindes : {sbp['name']} {a}, {bbp['name']} {b}.")
            self.advance_turn(bb_i)
        else:
            self.advance_turn(self.dealer)

    def next_street(self):
        if not self.hand_active:
            raise GameError("Aucune main en cours.")
        i = STREETS.index(self.street) if self.street in STREETS else 3
        if i >= 3:
            raise GameError("La river est déjà passée : désigne le gagnant.")
        self.street = STREETS[i + 1]
        for p in self.players:
            p["street_bet"] = 0
        names = {"flop": "Flop", "turn": "Turn", "river": "River"}
        self.add_log(f"{names[self.street]} — pot : {self.pot}.")
        self.advance_turn(self.dealer)

    def award(self, winner_ids):
        if not self.hand_active:
            raise GameError("Aucune main en cours.")
        if not winner_ids:
            raise GameError("Sélectionne au moins un gagnant.")
        winners = [self.player_by_id(w) for w in winner_ids]
        pot = self.pot
        share, rest = divmod(pot, len(winners))
        # le reste va au premier gagnant à gauche du donneur
        order = sorted(winners, key=lambda w: (self.idx(w) - self.dealer - 1) % len(self.players))
        for k, w in enumerate(order):
            w["stack"] += share + (1 if k < rest else 0)
        if len(winners) == 1:
            self.add_log(f"🏆 {winners[0]['name']} remporte le pot de {pot}.")
        else:
            self.add_log(f"🏆 Pot de {pot} partagé entre {', '.join(w['name'] for w in order)}.")
        self.finish_hand()

    def cancel_hand(self):
        if not self.hand_active:
            raise GameError("Aucune main en cours.")
        for p in self.players:
            p["stack"] += p["hand_bet"]
        self.add_log(f"Main n°{self.hand_number} annulée : chacun récupère ses mises.")
        self.finish_hand()

    def finish_hand(self):
        self.pot = 0
        self.hand_active = False
        self.street = None
        self.to_act = None
        for p in self.players:
            p["street_bet"] = 0
            p["hand_bet"] = 0
            p["folded"] = False
            p["in_hand"] = False

    def set_stack(self, pid, stack):
        p = self.player_by_id(pid)
        try:
            stack = int(stack)
        except (TypeError, ValueError):
            raise GameError("Montant invalide.")
        if stack < 0:
            raise GameError("Le tapis ne peut pas être négatif.")
        old = p["stack"]
        p["stack"] = stack
        self.add_log(f"Tapis de {p['name']} ajusté : {old} → {stack}.")

    def remove(self, pid):
        p = self.player_by_id(pid)
        if self.hand_active and p["hand_bet"] > 0:
            raise GameError("Ce joueur a des jetons dans le pot : termine la main d'abord.")
        i = self.idx(p)
        self.players.pop(i)
        if self.dealer >= i:
            self.dealer -= 1
        if self.to_act == p["id"]:
            self.advance_turn(max(i - 1, 0))
        self.add_log(f"{p['name']} quitte la table.")

    def set_blinds(self, sb, bb):
        try:
            sb, bb = int(sb), int(bb)
        except (TypeError, ValueError):
            raise GameError("Blindes invalides.")
        if sb < 0 or bb < 0 or (bb and sb > bb):
            raise GameError("Blindes invalides.")
        self.sb, self.bb = sb, bb
        self.add_log(f"Blindes : {sb}/{bb}." if bb else "Blindes désactivées.")

    # ---------- état public ----------
    def public(self, me_token):
        me = next((p for p in self.players if p["token"] == me_token), None)
        if me:
            me["last_seen"] = time.time()
        now = time.time()
        return {
            "code": self.code,
            "version": self.version,
            "pot": self.pot,
            "street": self.street,
            "handActive": self.hand_active,
            "handNumber": self.hand_number,
            "sb": self.sb,
            "bb": self.bb,
            "startStack": self.start_stack,
            "maxBet": self.max_bet(),
            "dealer": self.players[self.dealer]["id"] if 0 <= self.dealer < len(self.players) else None,
            "toAct": self.to_act,
            "players": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "stack": p["stack"],
                    "streetBet": p["street_bet"],
                    "handBet": p["hand_bet"],
                    "folded": p["folded"],
                    "inHand": p["in_hand"],
                    "online": now - p["last_seen"] < 8,
                }
                for p in self.players
            ],
            "log": self.log[-25:],
            "me": me["id"] if me else None,
        }


def cleanup():
    now = time.time()
    for code in [c for c, g in GAMES.items() if now - g.touched > GAME_TTL]:
        del GAMES[code]


class Handler(BaseHTTPRequestHandler):
    server_version = "PokerJetons/1.0"

    def log_message(self, fmt, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, name):
        path = os.path.join(STATIC, name)
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        if path in ("/", "/index.html"):
            return self.send_file("index.html")
        if path.startswith("/g/"):
            return self.send_file("table.html")
        if path == "/api/info":
            return self.send_json({"lanUrl": f"http://{lan_ip()}:{PORT}"})
        if path == "/api/state":
            q = parse_qs(url.query)
            code = (q.get("code") or [""])[0].upper()
            token = (q.get("token") or [""])[0]
            with LOCK:
                g = GAMES.get(code)
                if not g:
                    return self.send_json({"error": "Partie introuvable (elle a peut-être expiré)."}, 404)
                st = g.public(token)
                st["isHost"] = bool(token) and token == g.host_token
                return self.send_json(st)
        self.send_json({"error": "Introuvable"}, 404)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self.send_json({"error": "Requête invalide."}, 400)
        try:
            with LOCK:
                result = self.route(urlparse(self.path).path, data)
            self.send_json(result)
        except GameError as e:
            self.send_json({"error": str(e)}, 400)

    def route(self, path, d):
        if path == "/api/create":
            cleanup()
            try:
                stack = int(d.get("stack", 1000))
                sb = int(d.get("sb", 0))
                bb = int(d.get("bb", 0))
            except (TypeError, ValueError):
                raise GameError("Valeurs invalides.")
            if stack <= 0 or stack > 10_000_000:
                raise GameError("Tapis de départ invalide.")
            g = Game(stack, 0, 0)
            g.set_blinds(sb, bb)
            g.log.clear()
            p = g.join(d.get("name"))
            g.host_token = p["token"]
            GAMES[g.code] = g
            g.bump()
            return {"code": g.code, "token": p["token"]}

        code = str(d.get("code", "")).upper()
        g = GAMES.get(code)
        if not g:
            raise GameError("Partie introuvable (elle a peut-être expiré).")

        if path == "/api/join":
            p = g.join(d.get("name"))
            g.bump()
            return {"token": p["token"]}

        if path == "/api/action":
            p = g.player_by_token(d.get("token"))
            kind = d.get("type")
            if kind in ("fold", "check", "call", "bet", "allin"):
                g.act(p, kind, d.get("amount"))
            else:
                if p["token"] != g.host_token:
                    raise GameError("Seul l'organisateur peut faire ça.")
                if kind == "new_hand":
                    g.new_hand()
                elif kind == "next_street":
                    g.next_street()
                elif kind == "award":
                    g.award(d.get("winners") or [])
                elif kind == "cancel_hand":
                    g.cancel_hand()
                elif kind == "set_stack":
                    g.set_stack(d.get("player"), d.get("stack"))
                elif kind == "remove":
                    if d.get("player") == p["id"]:
                        raise GameError("L'organisateur ne peut pas se retirer.")
                    g.remove(d.get("player"))
                elif kind == "set_blinds":
                    g.set_blinds(d.get("sb"), d.get("bb"))
                else:
                    raise GameError("Action inconnue.")
            g.bump()
            return {"ok": True}

        raise GameError("Introuvable")


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    ip = lan_ip()
    print("\n  ♠ ♥  Poker Jetons est lancé  ♦ ♣\n")
    print(f"  Sur cet ordinateur :      http://localhost:{PORT}")
    print(f"  Depuis les téléphones :   http://{ip}:{PORT}   (même Wi-Fi)\n")
    print("  Ctrl+C pour arrêter.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
