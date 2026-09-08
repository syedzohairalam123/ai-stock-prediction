import {NavLink,Outlet} from "react-router-dom";
const LINKS=[
  ["/","◎","Command Center"],
  ["/macro","🌐","Macro"],
  ["/events","⚡","Events & Stress"],
  ["/company","🏢","Company"],
  ["/screener","🔎","Screener"],
  ["/crypto","🪙","Crypto Pro"],
  ["/analytics","📊","Regime Analytics"],
] as const;
export default function Layout(){
  return <div className="shell">
    <aside className="sidebar">
      <div>
        <span className="logo">NEURAL MARKET</span>
        <div className="tagline">AI market intelligence</div>
      </div>
      <nav className="side-links" aria-label="Primary">
        {LINKS.map(([to,icon,label])=><NavLink key={to} to={to} end={to==="/"} className={({isActive})=>isActive?"active":""}><span className="icon" aria-hidden>{icon}</span>{label}</NavLink>)}
      </nav>
      <div className="side-foot">Educational analytics only — not investment advice.</div>
    </aside>
    <main className="content"><Outlet/></main>
  </div>;
}
