#!/usr/bin/env python3
"""
BadgeNET fake IRC server for the Thotcon 0xC badge.

The badge (Fredi-Machado Arduino IRC client) connects to host 'TC0xCBADGE'
on tcp/6667, registers with NICK/USER, then auto-joins:
    JOIN #snowfield RAR
    JOIN #battles CONTRA
and plays "BadgeBattles" via PRIVMSG #battles.

This server implements just enough RFC1459 for the client to consider itself
registered and joined, logs EVERYTHING the badge sends (so we can reverse the
game protocol), and lets us inject arbitrary lines from the console or a script.

No root needed (port 6667 > 1024). Run:  python3 badgenet_server.py
Console: type 'raw <line>' to send a raw IRC line to all clients,
         'msg <chan> <text>' to PRIVMSG a channel, 'who' to list clients,
         'quit' to stop.
"""
import socket, threading, time, sys, argparse, datetime

SRV = "TC0xCBADGE"            # server name we present
MOTD = "Welcome to BadgeNET"

def ts():
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

class Client(threading.Thread):
    def __init__(self, conn, addr, hub):
        super().__init__(daemon=True)
        self.conn, self.addr, self.hub = conn, addr, hub
        self.nick = None
        self.user = None
        self.registered = False
        self.channels = set()
        self.buf = b""
        self.alive = True

    def send(self, line):
        try:
            self.conn.sendall((line + "\r\n").encode("utf-8", "replace"))
            print(f"[{ts()}] -> {self.addr[0]}: {line}")
        except OSError:
            self.alive = False

    def run(self):
        print(f"[{ts()}] ++ connect {self.addr}")
        self.conn.settimeout(600)
        try:
            while self.alive:
                try:
                    data = self.conn.recv(4096)
                except socket.timeout:
                    self.send(f"PING :{SRV}")
                    continue
                except OSError:
                    break
                if not data:
                    break
                self.buf += data
                while b"\n" in self.buf:
                    raw, self.buf = self.buf.split(b"\n", 1)
                    line = raw.rstrip(b"\r").decode("utf-8", "replace")
                    if line:
                        self.handle(line)
        finally:
            print(f"[{ts()}] -- disconnect {self.addr} (nick={self.nick})")
            self.hub.remove(self)
            try: self.conn.close()
            except OSError: pass

    def handle(self, line):
        print(f"[{ts()}] <- {self.addr[0]} ({self.nick}): {line}")
        parts = line.split(" ")
        cmd = parts[0].upper()
        if cmd == "PASS":
            pass  # accept any
        elif cmd == "NICK":
            self.nick = parts[1] if len(parts) > 1 else "badge"
            self.try_register()
        elif cmd == "USER":
            self.user = line
            self.try_register()
        elif cmd == "PING":
            token = line[5:] if len(line) > 5 else SRV
            self.send(f"PONG {SRV} :{token.lstrip(':')}")
        elif cmd == "PONG":
            pass
        elif cmd == "JOIN":
            chans = parts[1].split(",") if len(parts) > 1 else []
            for ch in chans:
                self.join(ch)
        elif cmd == "PRIVMSG":
            # the game plays out here -- just log; could auto-respond
            self.hub.relay(self, line)
        elif cmd == "QUIT":
            self.alive = False
        elif cmd == "VERSION":
            self.send(f":{SRV} 351 {self.nick} BadgeNET-fake :running")
        # everything else: ignore (log already printed)

    def try_register(self):
        if self.nick and self.user and not self.registered:
            self.registered = True
            n = self.nick
            self.send(f":{SRV} 001 {n} :Welcome to BadgeNET {n}")
            self.send(f":{SRV} 002 {n} :Your host is {SRV}, running fake-badgenet")
            self.send(f":{SRV} 003 {n} :This server was created just now")
            self.send(f":{SRV} 004 {n} {SRV} fake-1.0 o o")
            self.send(f":{SRV} 375 {n} :- {SRV} Message of the day -")
            self.send(f":{SRV} 372 {n} :- {MOTD}")
            self.send(f":{SRV} 376 {n} :End of /MOTD command")
            print(f"[{ts()}] ** {self.addr[0]} registered as {n}")

    def join(self, ch):
        self.channels.add(ch)
        n = self.nick
        # echo the JOIN back from the user's prefix so the client accepts it
        self.send(f":{n}!{n}@badge JOIN {ch}")
        self.send(f":{SRV} 332 {n} {ch} :BadgeBattles arena")
        self.send(f":{SRV} 353 {n} = {ch} :{n} TC_Opponent")
        self.send(f":{SRV} 366 {n} {ch} :End of /NAMES list")
        print(f"[{ts()}] ** {self.addr[0]} joined {ch}")

class Hub:
    def __init__(self):
        self.clients = []
        self.lock = threading.Lock()
    def add(self, c):
        with self.lock: self.clients.append(c)
    def remove(self, c):
        with self.lock:
            if c in self.clients: self.clients.remove(c)
    def relay(self, src, line):
        # A real server would forward to channel members; we just log.
        pass
    def broadcast_raw(self, line):
        with self.lock: cs = list(self.clients)
        for c in cs: c.send(line)
    def privmsg(self, chan, text, frm="TC_Opponent"):
        self.broadcast_raw(f":{frm}!{frm}@badge PRIVMSG {chan} :{text}")

def console(hub):
    print("console ready: raw <line> | msg <chan> <text> | who | quit")
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line: continue
        if line == "quit":
            import os; os._exit(0)
        elif line == "who":
            for c in hub.clients:
                print(f"  {c.addr} nick={c.nick} chans={c.channels}")
        elif line.startswith("raw "):
            hub.broadcast_raw(line[4:])
        elif line.startswith("msg "):
            _, chan, text = line.split(" ", 2)
            hub.privmsg(chan, text)
        else:
            print("  commands: raw <line> | msg <chan> <text> | who | quit")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=6667)
    args = ap.parse_args()
    hub = Hub()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(8)
    print(f"[{ts()}] BadgeNET IRC server listening on {args.host}:{args.port} as {SRV}")
    threading.Thread(target=console, args=(hub,), daemon=True).start()
    while True:
        conn, addr = srv.accept()
        c = Client(conn, addr, hub)
        hub.add(c)
        c.start()

if __name__ == "__main__":
    main()
