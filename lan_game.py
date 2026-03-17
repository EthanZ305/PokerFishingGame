import pygame
import random
import socket
import threading
import json
import sys
import time
import os

# --- 1. 基础配置 ---
pygame.init()
pygame.mixer.init()  # <-- [新增] 初始化音频引擎
W, H = 1050, 750
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("纸牌钓鱼：全能音效稳定版")

# 颜色
DARK_GREEN = (20, 70, 35)
GOLD = (255, 215, 0)
WHITE = (255, 255, 255)
BTN_COLOR = (45, 110, 160)
BTN_HOVER = (65, 140, 210)
CARD_W, CARD_H = 75, 105

# 字体
try:
    font_s = pygame.font.SysFont("SimHei", 20)
    font_m = pygame.font.SysFont("SimHei", 28)
    font_l = pygame.font.SysFont("SimHei", 60)
except:
    font_s = pygame.font.SysFont("arial", 20)
    font_m = pygame.font.SysFont("arial", 28)
    font_l = pygame.font.SysFont("arial", 60)


# --- 2. 工具类 ---
class UIButton:
    def __init__(self, x, y, w, h, text, color=BTN_COLOR):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = text
        self.color = color

    def draw(self, surf):
        m_pos = pygame.mouse.get_pos()
        c = BTN_HOVER if self.rect.collidepoint(m_pos) else self.color
        pygame.draw.rect(surf, c, self.rect, border_radius=10)
        pygame.draw.rect(surf, WHITE, self.rect, 2, border_radius=10)
        t = font_m.render(self.text, True, WHITE)
        surf.blit(t, t.get_rect(center=self.rect.center))


class AniCard:
    def __init__(self, img, start, end, callback=None):
        self.img = img
        self.pos = list(start)
        self.target = end
        self.dead = False
        self.callback = callback

    def update(self):
        if abs(self.pos[0] - self.target[0]) < 5 and abs(self.pos[1] - self.target[1]) < 5:
            self.dead = True
            if self.callback: self.callback()
        else:
            self.pos[0] += (self.target[0] - self.pos[0]) * 0.2
            self.pos[1] += (self.target[1] - self.pos[1]) * 0.2

    def draw(self, surf):
        surf.blit(self.img, (int(self.pos[0]), int(self.pos[1])))


# --- 3. 游戏引擎 ---
class PokerGame:
    def __init__(self):
        self.state = "LOBBY"
        self.my_id = 0
        self.conn = None
        self.status = "准备就绪"
        self.msg_queue = []
        self.card_imgs = {}
        self.hands = {1: [], 2: []}
        self.scores = {1: 0, 2: 0}
        self.table = []
        self.turn = 1
        self.animations = []
        self.pending_loot_idx = -1

        # 手动输入相关
        self.input_ip = ""
        self.show_keypad = False

        # 按钮
        self.btn_h = UIButton(W // 2 - 220, 350, 200, 70, "创建房间")
        self.btn_j = UIButton(W // 2 + 20, 350, 200, 70, "自动加入")
        self.btn_manual = UIButton(W - 160, H - 60, 140, 40, "手动输入IP", (80, 80, 80))
        self.btn_s = UIButton(W // 2 - 100, 450, 200, 70, "开始发牌", (180, 120, 30))
        self.btn_loot = UIButton(W // 2 - 100, H // 2 + 80, 200, 60, "点击收牌！", (200, 50, 50))
        self.btn_restart = UIButton(W // 2 - 100, H // 2 + 100, 200, 60, "重新开始")

        # 数字键盘按钮
        self.num_btns = []
        keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '.', '退格']
        for i, k in enumerate(keys):
            x = W // 2 - 165 + (i % 3) * 115
            y = 420 + (i // 3) * 60
            color = (120, 40, 40) if k == '退格' else (60, 60, 60)
            self.num_btns.append(UIButton(x, y, 100, 50, k, color))
        self.btn_confirm = UIButton(W // 2 - 100, 670, 200, 50, "确认连接", (30, 150, 30))

        # [新增] 音频属性
        self.snd_play = None
        self.snd_collect = None
        self.load_sounds()

    def load_sounds(self):
        """ [新增] 加载音频资源 """
        if not os.path.exists("sounds"):
            os.makedirs("sounds")
        try:
            if os.path.exists("sounds/bgm.mp3"):
                pygame.mixer.music.load("sounds/bgm.mp3")
                pygame.mixer.music.set_volume(0.1)
                pygame.mixer.music.play(-1)
            if os.path.exists("sounds/play.wav"):
                self.snd_play = pygame.mixer.Sound("sounds/play.wav")
            if os.path.exists("sounds/collect.wav"):
                self.snd_collect = pygame.mixer.Sound("sounds/collect.wav")
        except:
            pass

    def preload(self):
        if self.card_imgs: return
        suits = ['spade', 'heart', 'club', 'diamond']
        ranks = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
        names = [f"{s}_{r}" for s in suits for r in ranks] + ["joker_big", "joker_small", "card_back"]
        for n in names:
            try:
                img = pygame.image.load(f"images/{n}.png").convert_alpha()
                self.card_imgs[n] = pygame.transform.smoothscale(img, (CARD_W, CARD_H))
            except:
                s = pygame.Surface((CARD_W, CARD_H));
                s.fill((200, 200, 200))
                self.card_imgs[n] = s

    def get_my_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80));
            ip = s.getsockname()[0];
            s.close()
            return ip
        except:
            return "127.0.0.1"

    def start_net(self, mode, target_ip=None):
        self.preload()
        if mode == "HOST":
            self.my_id = 1
            self.status = f"我的IP: {self.get_my_ip()}"
            threading.Thread(target=self._server, daemon=True).start()
            threading.Thread(target=self._broadcast, daemon=True).start()
        elif mode == "GUEST_AUTO":
            self.my_id = 2
            threading.Thread(target=self._discovery, daemon=True).start()
        elif mode == "GUEST_MANUAL":
            self.my_id = 2
            self.status = f"尝试连接 {target_ip}..."
            threading.Thread(target=self._connect, args=(target_ip,), daemon=True).start()

    def _broadcast(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while not self.conn:
            try:
                s.sendto(b"POKER_DISC", ('<broadcast>', 9998));
                time.sleep(1)
            except:
                break

    def _discovery(self):
        self.status = "搜寻房主中..."
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(('', 9998));
        s.settimeout(5.0)
        try:
            data, addr = s.recvfrom(1024)
            if data == b"POKER_DISC": self._connect(addr[0])
        except:
            self.status = "未发现房间"

    def _server(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', 9999));
        s.listen(1)
        self.conn, _ = s.accept()
        self.status = "对手已连入！"
        self._listen()

    def _connect(self, ip):
        try:
            self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.conn.connect((ip, 9999))
            self.status = "连接成功！"
            self._listen()
        except:
            self.status = "连接失败"

    def _listen(self):
        while True:
            try:
                d = self.conn.recv(4096).decode('utf-8')
                if d: self.msg_queue.append(json.loads(d))
            except:
                break

    def send(self, data):
        if self.conn: self.conn.send(json.dumps(data).encode('utf-8'))

    def sync_deal(self):
        # [新增] 发牌时响一下出牌音效
        if self.snd_play: self.snd_play.play()
        deck = [n for n in self.card_imgs.keys() if n != "card_back"]
        random.shuffle(deck)
        self.send({"type": "INIT", "deck": deck})
        self._init_game(deck)

    def _init_game(self, deck):
        self.hands[1], self.hands[2] = deck[:27], deck[27:]
        self.scores = {1: 0, 2: 0};
        self.table = [];
        self.state = "PLAYING"

    def _exec_play(self, card):
        # [新增] 播放出牌音效
        if self.snd_play: self.snd_play.play()

        rank = "JOKER" if "joker" in card else card.split('_')[1]
        m_idx = -1
        for i, tc in enumerate(self.table):
            tr = "JOKER" if "joker" in tc else tc.split('_')[1]
            if rank == tr: m_idx = i; break
        sy = H - 150 if self.turn == self.my_id else 50

        def done():
            self.table.append(card)
            if m_idx != -1:
                self.pending_loot_idx = m_idx
            else:
                self._check_next_turn()

        self.animations.append(
            AniCard(self.card_imgs[card], (W // 2, sy), (150 + len(self.table) * 30, H // 2 - 50), done))

    def _exec_collect(self):
        # [新增] 播放收牌音效
        if self.snd_collect: self.snd_collect.play()

        loot_count = len(self.table) - self.pending_loot_idx
        self.scores[self.turn] += loot_count
        self.table = self.table[:self.pending_loot_idx]
        self.pending_loot_idx = -1
        self._check_next_turn()

    def _check_next_turn(self):
        self.turn = 2 if self.turn == 1 else 1
        if not self.hands[1] and not self.hands[2] and not self.animations: self.state = "END"

    def update(self):
        while self.msg_queue:
            m = self.msg_queue.pop(0)
            if m["type"] == "INIT": self._init_game(m["deck"])
            if m["type"] == "PLAY": self._exec_play(m["card"])
            if m["type"] == "COLLECT": self._exec_collect()
            if m["type"] == "RESTART": self.state = "LOBBY"; self.my_id = 0; self.conn = None
        for a in self.animations[:]:
            a.update()
            if a.dead: self.animations.remove(a)

    def draw(self, surf):
        surf.fill(DARK_GREEN)
        if self.state == "LOBBY":
            t = font_l.render("纸牌钓鱼：全能对战版", True, GOLD)
            surf.blit(t, (W // 2 - t.get_width() // 2, 100))
            st = font_m.render(self.status, True, WHITE)
            surf.blit(st, (W // 2 - st.get_width() // 2, 280))

            if not self.my_id:
                self.btn_h.draw(surf);
                self.btn_j.draw(surf);
                self.btn_manual.draw(surf)
            elif self.my_id == 1 and self.conn:
                self.btn_s.draw(surf)
            elif self.my_id == 2 and not self.conn and self.show_keypad:
                pygame.draw.rect(surf, WHITE, (W // 2 - 150, 360, 300, 45), 2)
                ip_t = font_m.render(self.input_ip + "_", True, GOLD)
                surf.blit(ip_t, (W // 2 - 140, 368))
                for b in self.num_btns: b.draw(surf)
                self.btn_confirm.draw(surf)

        elif self.state == "PLAYING":
            opp = 2 if self.my_id == 1 else 1
            for i in range(len(self.hands[opp])): surf.blit(self.card_imgs["card_back"], (50 + i * 25, 20))
            for i, c in enumerate(self.table): surf.blit(self.card_imgs[c], (150 + i * 30, H // 2 - 50))
            for i, c in enumerate(self.hands[self.my_id]): surf.blit(self.card_imgs[c], (50 + i * 30, H - CARD_H - 20))

            panel_w, panel_h = 160, 120
            panel_x, panel_y = W - panel_w - 20, H // 2 - panel_h // 2
            pygame.draw.rect(surf, (0, 0, 0, 140), (panel_x, panel_y, panel_w, panel_h), border_radius=12)
            pygame.draw.rect(surf, GOLD, (panel_x, panel_y, panel_w, panel_h), 2, border_radius=12)
            surf.blit(font_s.render("─实时比分─", True, WHITE), (panel_x + 25, panel_y + 15))
            surf.blit(font_m.render(f"对方: {self.scores[opp]}", True, WHITE), (panel_x + 30, panel_y + 45))
            surf.blit(font_m.render(f"我方: {self.scores[self.my_id]}", True, GOLD), (panel_x + 30, panel_y + 75))

            txt = "★ 你的回合 ★" if self.turn == self.my_id else "等待对方行动..."
            if self.turn == self.my_id and self.pending_loot_idx != -1: self.btn_loot.draw(surf)
            prompt = font_m.render(txt, True, GOLD);
            surf.blit(prompt, (W // 2 - prompt.get_width() // 2, H - CARD_H - 60))

        elif self.state == "END":
            opp = 2 if self.my_id == 1 else 1
            win = self.scores[self.my_id] > self.scores[opp]
            res = "你赢了！恭喜！" if win else "你输了，再接再厉！"
            if self.scores[self.my_id] == self.scores[opp]: res = "平局！"
            t_res = font_l.render(res, True, GOLD if win else WHITE)
            surf.blit(t_res, (W // 2 - t_res.get_width() // 2, H // 2 - 100))
            self.btn_restart.draw(surf)

        for a in self.animations: a.draw(surf)


def main():
    game = PokerGame()
    clock = pygame.time.Clock()
    while True:
        game.update()
        for e in pygame.event.get():
            if e.type == pygame.QUIT: pygame.quit(); sys.exit()
            if e.type == pygame.MOUSEBUTTONDOWN:
                if game.state == "LOBBY":
                    if not game.my_id:
                        if game.btn_h.rect.collidepoint(e.pos): game.start_net("HOST")
                        if game.btn_j.rect.collidepoint(e.pos): game.start_net("GUEST_AUTO")
                        if game.btn_manual.rect.collidepoint(e.pos): game.show_keypad = True; game.my_id = 2
                    elif game.my_id == 1 and game.conn:
                        if game.btn_s.rect.collidepoint(e.pos): game.sync_deal()
                    elif game.my_id == 2 and not game.conn and game.show_keypad:
                        for b in game.num_btns:
                            if b.rect.collidepoint(e.pos):
                                if b.text == "退格":
                                    game.input_ip = game.input_ip[:-1]
                                elif len(game.input_ip) < 15:
                                    game.input_ip += b.text
                        if game.btn_confirm.rect.collidepoint(e.pos):
                            game.start_net("GUEST_MANUAL", game.input_ip)
                elif game.state == "PLAYING" and game.turn == game.my_id:
                    if game.pending_loot_idx != -1:
                        if game.btn_loot.rect.collidepoint(e.pos): game.send({"type": "COLLECT"}); game._exec_collect()
                    elif H - CARD_H - 20 < e.pos[1] < H - 20:
                        idx = (e.pos[0] - 50) // 30
                        if 0 <= idx < len(game.hands[game.my_id]):
                            c = game.hands[game.my_id].pop(idx)
                            game.send({"type": "PLAY", "card": c});
                            game._exec_play(c)
                elif game.state == "END":
                    if game.btn_restart.rect.collidepoint(e.pos):
                        game.send({"type": "RESTART"});
                        game.state = "LOBBY";
                        game.my_id = 0;
                        game.conn = None
        game.draw(screen);
        pygame.display.flip();
        clock.tick(60)


if __name__ == "__main__": main()