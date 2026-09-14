import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import BaseCard from "../components/BaseCard";
import BaseInput from "../components/BaseInput";
import BaseButton from "../components/BaseButton";
import { Mail, Lock } from "lucide-react";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    // Accounts aren't wired up yet. Say so honestly instead of pretending the
    // sign-in succeeded — every analytics feature is already open without it.
    setNotice("Accounts aren't enabled in this build yet — all analytics are open without signing in.");
  }

  return (
    <div className="auth-wrap">
      <BaseCard className="auth-card" padding="lg">
        <h1 className="auth-title">Welcome back</h1>
        <p className="auth-sub">Sign in to your Neural Market terminal.</p>
        <form onSubmit={submit}>
          <BaseInput
            label="Email"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            leftIcon={<Mail size={16} />}
            required
          />
          <BaseInput
            label="Password"
            type="password"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            leftIcon={<Lock size={16} />}
            required
          />
          <BaseButton type="submit" fullWidth size="lg">
            Sign In
          </BaseButton>
        </form>
        {notice && <p className="auth-alt" role="status">{notice}</p>}
        <p className="auth-alt">
          New here? <Link to="/signup">Create an account</Link>
        </p>
      </BaseCard>
    </div>
  );
}