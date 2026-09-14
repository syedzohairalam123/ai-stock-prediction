import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import BaseCard from "../components/BaseCard";
import BaseInput from "../components/BaseInput";
import BaseButton from "../components/BaseButton";
import { Mail, Lock, User } from "lucide-react";

export default function SignupPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    // No account backend yet — never imply an account was created.
    setNotice("Account creation isn't enabled in this build yet — every feature is already available without an account.");
  }

  return (
    <div className="auth-wrap">
      <BaseCard className="auth-card" padding="lg">
        <h1 className="auth-title">Create your account</h1>
        <p className="auth-sub">Free PSX financial terminal access.</p>
        <form onSubmit={submit}>
          <BaseInput
            label="Full name"
            placeholder="Your name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            leftIcon={<User size={16} />}
            required
          />
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
            placeholder="Minimum 8 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            leftIcon={<Lock size={16} />}
            required
          />
          <BaseButton type="submit" fullWidth size="lg">
            Sign Up
          </BaseButton>
        </form>
        {notice && <p className="auth-alt" role="status">{notice}</p>}
        <p className="auth-alt">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </BaseCard>
    </div>
  );
}