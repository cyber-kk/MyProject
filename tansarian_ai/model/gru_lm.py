"""A compact GRU language model implemented in pure NumPy (CPU friendly).

Runs comfortably on Termux / any modest CPU:
  - embedding + 1-layer GRU + output projection
  - full BPTT training with Adam and gradient clipping
  - temperature / top-k sampling with banned-token masking
Weights persist as a single .npz file shipped with the project.
"""
import numpy as np


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _softmax(x):
    x = x - x.max(axis=-1, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=-1, keepdims=True)


class GRULM:
    def __init__(self, vocab_size, embed_dim=96, hidden_dim=192, seed=7):
        self.V = int(vocab_size)
        self.H = int(hidden_dim)
        self.E = int(embed_dim)
        rng = np.random.default_rng(seed)
        self.params = {
            "emb": (rng.standard_normal((self.V, self.E)) * 0.08).astype(np.float32),
            "Wz": (rng.standard_normal((self.E, self.H)) / np.sqrt(self.E)).astype(np.float32),
            "Uz": (rng.standard_normal((self.H, self.H)) / np.sqrt(self.H)).astype(np.float32),
            "bz": np.zeros(self.H, dtype=np.float32),
            "Wr": (rng.standard_normal((self.E, self.H)) / np.sqrt(self.E)).astype(np.float32),
            "Ur": (rng.standard_normal((self.H, self.H)) / np.sqrt(self.H)).astype(np.float32),
            "br": np.zeros(self.H, dtype=np.float32),
            "Wn": (rng.standard_normal((self.E, self.H)) / np.sqrt(self.E)).astype(np.float32),
            "Un": (rng.standard_normal((self.H, self.H)) / np.sqrt(self.H)).astype(np.float32),
            "bn": np.zeros(self.H, dtype=np.float32),
            "Wo": (rng.standard_normal((self.H, self.V)) / np.sqrt(self.H)).astype(np.float32),
            "bo": np.zeros(self.V, dtype=np.float32),
        }

    # ---------------------------------------------------------------- forward
    def forward(self, ids, h0=None, cache=False):
        """ids: (B, T) int array of inputs. Returns logits (B, T, V)."""
        B, T = ids.shape
        p = self.params
        h = np.zeros((B, self.H), dtype=np.float32) if h0 is None else h0.copy()
        hs, zs, rs, ns, rs_h, logits = [], [], [], [], [], []
        for t in range(T):
            x = p["emb"][ids[:, t]]
            z = _sigmoid(x @ p["Wz"] + h @ p["Uz"] + p["bz"])
            r = _sigmoid(x @ p["Wr"] + h @ p["Ur"] + p["br"])
            rh = r * h
            n = np.tanh(x @ p["Wn"] + rh @ p["Un"] + p["bn"])
            h = (1.0 - z) * h + z * n
            hs.append(h)
            zs.append(z)
            rs.append(r)
            ns.append(n)
            rs_h.append(rh)
        flat = np.stack(hs, axis=1)  # (B, T, H) -- b-major ordering!
        logits = flat @ p["Wo"] + p["bo"]  # (B, T, V)
        if cache:
            self._cache = {"ids": ids, "hs": hs, "zs": zs, "rs": rs, "ns": ns, "rs_h": rs_h}
        return logits

    def loss_and_grads(self, ids, targets):
        """Mean cross-entropy over (B, T); returns loss and grads dict."""
        B, T = ids.shape
        logits = self.forward(ids, cache=True)
        c = self._cache
        p = self.params

        logits2 = logits.reshape(B * T, self.V)
        probs = _softmax(logits2)
        tgt = targets.reshape(B * T)
        eps = 1e-12
        loss = float(-np.mean(np.log(probs[np.arange(len(tgt)), tgt] + eps)))

        dlogits = probs.astype(probs.dtype)
        dlogits[np.arange(len(tgt)), tgt] -= 1.0
        dlogits /= (B * T)

        grads = {k: np.zeros_like(v) for k, v in p.items()}

        # output layer
        hs_arr = np.stack(c["hs"], axis=1)  # (B, T, H)
        dl3 = dlogits.reshape(B, T, self.V)
        grads["Wo"][:] = np.tensordot(hs_arr, dl3, axes=([0, 1], [0, 1]))
        grads["bo"][:] = dl3.sum(axis=(0, 1))

        dh_next = (dl3 @ p["Wo"].T)  # (B, T, H) grad wrt each h_t

        dh = np.zeros((B, self.H))
        for t in reversed(range(T)):
            dh = dh + dh_next[:, t, :]
            h_t = c["hs"][t]
            h_prev = c["hs"][t - 1] if t > 0 else np.zeros((B, self.H))
            z_t, r_t, n_t, rh_t = c["zs"][t], c["rs"][t], c["ns"][t], c["rs_h"][t]
            x_t = p["emb"][ids[:, t]]

            dz = dh * (n_t - h_prev)
            dh_prev = dh * (1.0 - z_t)
            dn = dh * z_t
            dn_raw = dn * (1.0 - n_t * n_t)

            # n = tanh(x Wn + (r*h) Un + bn)
            grads["Wn"] += x_t.T @ dn_raw
            grads["Un"] += rh_t.T @ dn_raw
            grads["bn"] += dn_raw.sum(axis=0)

            d_rh = dn_raw @ p["Un"].T
            dr = d_rh * h_prev
            dh_prev = dh_prev + d_rh * r_t

            dr_raw = dr * r_t * (1.0 - r_t)
            dz_raw = dz * z_t * (1.0 - z_t)

            # h_prev also feeds the z/r gates at this timestep via Uz/Ur:
            # dL/dh_prev += dL/dz_raw @ Uz.T + dL/dr_raw @ Ur.T
            dh_prev = dh_prev + dz_raw @ p["Uz"].T + dr_raw @ p["Ur"].T

            grads["Wz"] += x_t.T @ dz_raw
            grads["Uz"] += h_prev.T @ dz_raw
            grads["bz"] += dz_raw.sum(axis=0)

            grads["Wr"] += x_t.T @ dr_raw
            grads["Ur"] += h_prev.T @ dr_raw
            grads["br"] += dr_raw.sum(axis=0)

            dx = dz_raw @ p["Wz"].T + dr_raw @ p["Wr"].T + dn_raw @ p["Wn"].T
            np.add.at(grads["emb"], ids[:, t], dx)

            dh = dh_prev

        # clip by global norm
        gnorm = np.sqrt(sum(float((g * g).sum()) for g in grads.values()))
        if gnorm > 5.0:
            scale = 5.0 / (gnorm + 1e-12)
            for k in grads:
                grads[k] *= scale
        return loss, grads

    # ---------------------------------------------------------------- sampling
    def sample(self, tok, seed_ids, max_tokens=40, temperature=0.75, top_k=12,
               ban_ids=(), rng=None):
        """Greedy-ish sampling. seed_ids: list of token ids."""
        rng = rng or np.random.default_rng()
        ban = set(int(b) for b in ban_ids)
        ids = list(seed_ids)
        out_ids = []
        h = None
        B = 1
        for _ in range(int(max_tokens)):
            # feed the last context window
            ctx = np.array(ids[-64:], dtype=np.int64).reshape(1, -1)
            logits = self.forward(ctx)
            lg = logits[0, -1].astype(np.float64)
            for b in ban:
                lg[b] = -1e9
            if temperature <= 0:
                nxt = int(np.argmax(lg))
            else:
                lg /= max(1e-6, temperature)
                if top_k and top_k > 0:
                    kth = np.partition(lg, -top_k)[-top_k]
                    lg[lg < kth] = -1e9
                pr = np.exp(lg - lg.max())
                pr /= pr.sum()
                nxt = int(rng.choice(len(pr), p=pr))
            if nxt == tok.vocab.get("<eos>"):
                break
            ids.append(nxt)
            out_ids.append(nxt)
        return out_ids

    # ------------------------------------------------------------ persistence
    def save(self, path):
        np.savez_compressed(path, **self.params)

    @classmethod
    def load(cls, path):
        data = np.load(path)
        V = data["emb"].shape[0]
        m = cls(vocab_size=V,
                embed_dim=int(data["emb"].shape[1]),
                hidden_dim=int(data["Wz"].shape[1]))
        for k in m.params:
            m.params[k] = data[k]
        return m


# ------------------------------------------------------------------ training
class Adam:
    def __init__(self, params, lr=2e-3, b1=0.9, b2=0.999, eps=1e-8):
        self.lr = lr
        self.b1, self.b2, self.eps = b1, b2, eps
        self.m = {k: np.zeros_like(v, dtype=np.float32) for k, v in params.items()}
        self.v = {k: np.zeros_like(v, dtype=np.float32) for k, v in params.items()}
        self.t = 0

    def step(self, params, grads):
        self.t += 1
        b1t = 1.0 - self.b1 ** self.t
        b2t = 1.0 - self.b2 ** self.t
        for k in params:
            g = grads[k].astype(np.float32)
            self.m[k] = self.b1 * self.m[k] + (1 - self.b1) * g
            self.v[k] = self.b2 * self.v[k] + (1 - self.b2) * (g * g)
            mhat = self.m[k] / b1t
            vhat = self.v[k] / b2t
            params[k] -= (self.lr * mhat / (np.sqrt(vhat) + self.eps)).astype(np.float32)


def train_lm(model, data_ids, epochs=40, batch_size=16, seq_len=48, lr=2e-3,
             seed=7, log_every=200, min_lr_ratio=0.15):
    """Train on a flat token stream with random chunk batches."""
    rng = np.random.default_rng(seed)
    opt = Adam(model.params, lr=lr)
    n = len(data_ids)
    max_start = n - seq_len - 1
    if max_start < batch_size:
        raise ValueError("corpus too small for training (need more tokens)")
    total_steps = max(1, (n // (batch_size * seq_len)) * epochs)
    step = 0
    running = []
    for epoch in range(epochs):
        starts = rng.integers(0, max_start, size=max(1, n // (batch_size * seq_len)))
        for s0 in starts:
            batch_x = np.zeros((batch_size, seq_len), dtype=np.int64)
            batch_y = np.zeros((batch_size, seq_len), dtype=np.int64)
            for b in range(batch_size):
                s = int(s0) + b * 7  # decorrelate rows
                s = min(s, max_start)
                batch_x[b] = data_ids[s:s + seq_len]
                batch_y[b] = data_ids[s + 1:s + seq_len + 1]
            loss, grads = model.loss_and_grads(batch_x, batch_y)
            # cosine-ish decay
            frac = min(1.0, step / total_steps)
            opt.lr = lr * (min_lr_ratio + (1 - min_lr_ratio) * 0.5 * (1 + np.cos(np.pi * frac)))
            opt.step(model.params, grads)
            running.append(loss)
            step += 1
            if log_every and step % log_every == 0:
                print("  epoch %d step %d | loss %.4f | ppl %.2f"
                      % (epoch + 1, step, float(np.mean(running[-log_every:])),
                         float(np.exp(np.mean(running[-log_every:])))))
    final = float(np.mean(running[-100:])) if running else float("inf")
    return final
