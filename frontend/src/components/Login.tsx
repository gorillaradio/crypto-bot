import { useState } from "react";
import { login } from "../api";

export function Login({ onAuthed }: { onAuthed: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError("");
    try {
      const { role } = await login(password);
      if (role === "admin") onAuthed();
      else setError("password errata");
    } catch {
      setError("password errata");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <span className="logo">crypto<b>·</b>bot</span>
        <label htmlFor="login-password">Password</label>
        <input id="login-password" type="password" value={password} autoFocus
          onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="modal-error">{error}</p>}
        <button type="submit" className="btn-primary" disabled={!password || busy}>Entra</button>
      </form>
    </div>
  );
}
