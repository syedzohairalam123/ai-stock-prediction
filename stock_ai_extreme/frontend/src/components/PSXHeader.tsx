import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link, useLocation } from 'react-router-dom';
import { Search, Menu, X, Settings, Sun, Moon, Smartphone, LogIn, UserPlus, ChevronDown, Gamepad2, Bitcoin } from 'lucide-react';

interface PSXHeaderProps {
  theme: 'light' | 'dark';
  toggleTheme: () => void;
  isMobileMenuOpen: boolean;
  toggleMobileMenu: () => void;
  onSearchOpen: () => void;
}

export default function PSXHeader({ theme, toggleTheme, isMobileMenuOpen, toggleMobileMenu, onSearchOpen }: PSXHeaderProps) {
  const location = useLocation();

  const navLinks = [
    { path: '/', label: 'Home' },
    // Phase 19: market discovery (trending / new / popular / recent feeds)
    { path: '/discover', label: 'Discover' },
    { path: '/market', label: 'Market' },
    { path: '/charts', label: 'Charts' },
    // Phase 21C: esports gets a primary slot (it is a first-class hub, not a
    // utility page) with its own icon so it reads as a distinct product area.
    { path: '/esports', label: 'Esports', icon: Gamepad2 },
    // Phase 22C: crypto terminal gets a primary slot too (real-time crypto
    // market hub) with its own icon, mirroring the esports treatment.
    { path: '/crypto-terminal', label: 'Crypto Terminal', icon: Bitcoin },
    { path: '/forex-commodities', label: 'Forex & Commodities' },
    { path: '/sentiment', label: 'Sentiment' },
    { path: '/forecasts', label: 'Forecasts' },
    // Phase 17: breaking news + trending topics + market impact desk
    { path: '/breaking-news', label: 'Breaking' },
    // Phase 18: neutral political/geopolitical map + timeline
    { path: '/political', label: 'Geopolitics' },
    { path: '/announcements', label: 'Announcements' },
    { path: '/news', label: 'News' },
    { path: '/watchlist', label: 'Watchlist' },
    { path: '/popular', label: 'Popular' },
    { path: '/portfolio/transactions', label: 'Portfolio' },
  ];

  /*
   * Phase 21C: everything with a real route that the primary nav has no room

   * for lives in a "More" dropdown. Nothing is removed from this list — these
   * are additive entries so every page in the app is reachable from the header.
   */
  const moreLinks = [
    { path: '/quant-lab', label: 'Quant Lab', group: 'Analytics' },
    { path: '/analytics', label: 'Analytics', group: 'Analytics' },
    { path: '/command-center', label: 'Command Center', group: 'Analytics' },
    { path: '/macro', label: 'Macro', group: 'Analytics' },
    { path: '/events', label: 'Events', group: 'Analytics' },
    { path: '/company', label: 'Company', group: 'Analytics' },
    { path: '/crypto', label: 'Crypto', group: 'Markets' },
    { path: '/crypto-terminal', label: 'Crypto Terminal', group: 'Markets' },
    { path: '/derivatives', label: 'Derivatives', group: 'Markets' },
    { path: '/screener', label: 'Screener', group: 'Tools' },
    { path: '/screener-classic', label: 'Screener Classic', group: 'Tools' },
    { path: '/compare', label: 'Compare', group: 'Tools' },
    { path: '/topics', label: 'Topics', group: 'News & Data' },
    { path: '/topics/:topicId', label: 'Topic detail', group: 'News & Data', hidden: true },
    { path: '/alerts', label: 'Alerts', group: 'Account' },
    { path: '/portfolio', label: 'Portfolio (holdings)', group: 'Account' },
    { path: '/workspace', label: 'Workspace', group: 'Account' },
    { path: '/settings', label: 'Settings', group: 'Account' },
  ].filter((link) => !link.hidden);

  const moreMatchesActive = moreLinks.some(
    (link) => link.path !== '/topics/:topicId' && location.pathname.startsWith(link.path)
  );
  const [moreOpen, setMoreOpen] = useState(false);
  const moreRef = useRef<HTMLDivElement | null>(null);

  // Close the dropdown on outside click or Escape (a11y: keyboard dismissable).
  useEffect(() => {
    if (!moreOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(event.target as Node)) setMoreOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMoreOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [moreOpen]);

  // Route changes always collapse the menu.
  useEffect(() => {
    setMoreOpen(false);
  }, [location.pathname]);

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/';
    return location.pathname.startsWith(path);
  };

  return (
    <header className="psx-header">
      <div className="psx-header-container">
        {/* Logo Section */}
        <div className="psx-header-left">
          <Link to="/" className="psx-logo">
            <div className="psx-logo-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3 3v18h18" />
                <path d="M18.7 8l-5.1 5.2-2.8-2.7L7 14.3" />
              </svg>
            </div>
            <div className="psx-logo-text">
              <span className="psx-logo-name">NEURAL MARKET</span>
              <span className="psx-logo-tagline">PSX Financial Terminal</span>
            </div>
          </Link>
        </div>

        {/* Global Search (opens the search modal) */}
        <div className="psx-header-search">
          <button className="psx-search-container" onClick={onSearchOpen} aria-label="Open global search">
            <Search className="psx-search-icon" size={16} />
            <span className="psx-search-input">Search stocks, sectors, indices…</span>
          </button>
        </div>

        {/* Desktop Navigation */}
        <nav className="psx-header-nav" aria-label="Primary">
          {navLinks.map((link) => (
            <Link
              key={link.path}
              to={link.path}
              className={`psx-nav-link ${isActive(link.path) ? 'active' : ''}`}
            >
              {link.icon ? (
                <>
                  <link.icon size={14} aria-hidden="true" /> {link.label}
                </>
              ) : (
                link.label
              )}
            </Link>
          ))}

          {/* Phase 21C "More" menu: every remaining page, grouped, keyboard
              accessible (button + aria-expanded, Escape closes). */}
          <div className="psx-nav-more" ref={moreRef}>
            <button
              type="button"
              className={`psx-nav-link psx-nav-more-toggle ${moreMatchesActive ? 'active' : ''}`}
              aria-haspopup="menu"
              aria-expanded={moreOpen}
              onClick={() => setMoreOpen((open) => !moreOpen)}
            >
              More <ChevronDown size={13} aria-hidden="true" />
            </button>
            {moreOpen && (
              <div className="psx-nav-more-menu" role="menu" aria-label="More pages">
                {Object.entries(
                  moreLinks.reduce<Record<string, typeof moreLinks>>((groups, link) => {
                    (groups[link.group] ||= []).push(link);
                    return groups;
                  }, {})
                ).map(([group, links]) => (
                  <div key={group} className="psx-nav-more-group" role="none">
                    <span className="psx-nav-more-group-label" role="presentation">{group}</span>
                    {links.map((link) => (
                      <Link
                        key={link.path}
                        to={link.path}
                        role="menuitem"
                        className={`psx-nav-more-item ${location.pathname.startsWith(link.path) ? 'active' : ''}`}
                      >
                        {link.label}
                      </Link>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        </nav>

        {/* Right Actions */}
        <div className="psx-header-right">
          {/* Theme Toggle */}
          <button
            className="psx-icon-btn"
            onClick={toggleTheme}
            aria-label="Toggle theme"
            title="Toggle dark/light mode"
          >
            {theme === 'light' ? <Moon size={20} /> : <Sun size={20} />}
          </button>

          {/* Settings */}
          <Link to="/settings" className="psx-icon-btn" aria-label="Settings" title="Settings">
            <Settings size={20} />
          </Link>

          {/* Auth Buttons */}
          <div className="psx-auth-buttons">
            <Link to="/login" className="psx-btn psx-btn-secondary">
              <LogIn size={16} />
              Login
            </Link>
            <Link to="/signup" className="psx-btn psx-btn-primary">
              <UserPlus size={16} />
              Sign Up
            </Link>
          </div>

          {/* Mobile Menu Toggle */}
          <button
            className="psx-mobile-toggle"
            onClick={toggleMobileMenu}
            aria-label="Toggle menu"
          >
            {isMobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
        </div>
      </div>

      {/* Mobile Menu — rendered through a portal on <body> because the header's
          backdrop-filter makes the header the containing block for fixed
          descendants (CSS spec), which collapsed the overlay to the header's
          height (~158px on phones): the drawer was visually clipped and taps
          below it fell through to the page underneath. Portalling restores the
          designed full-viewport overlay without touching the header styles. */}
      {isMobileMenuOpen && createPortal(
        <div className="psx-mobile-menu open" onClick={toggleMobileMenu}>
          <div className="psx-mobile-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="psx-mobile-drawer-head">
              <span className="psx-logo-name">NEURAL MARKET</span>
              <button className="psx-icon-btn" onClick={toggleMobileMenu} aria-label="Close menu">
                <X size={20} />
              </button>
            </div>
            <nav className="psx-mobile-nav">
              {navLinks.map((link) => (
                <Link
                  key={link.path}
                  to={link.path}
                  className={`psx-mobile-nav-link ${isActive(link.path) ? 'active' : ''}`}
                  onClick={toggleMobileMenu}
                >
                  {link.label}
                </Link>
              ))}
              {/* Phase 21C: the mobile drawer also carries every page, grouped
                  under the same labels as the desktop "More" menu. */}
              {Object.entries(
                moreLinks.reduce<Record<string, typeof moreLinks>>((groups, link) => {
                  (groups[link.group] ||= []).push(link);
                  return groups;
                }, {})
              ).map(([group, links]) => (
                <div key={group} className="psx-mobile-nav-group">
                  <span className="psx-mobile-nav-group-label">{group}</span>
                  {links.map((link) => (
                    <Link
                      key={link.path}
                      to={link.path}
                      className={`psx-mobile-nav-link psx-mobile-nav-sub ${isActive(link.path) ? 'active' : ''}`}
                      onClick={toggleMobileMenu}
                    >
                      {link.label}
                    </Link>
                  ))}
                </div>
              ))}
            </nav>
            <div className="psx-mobile-auth">
              <Link to="/login" className="psx-btn psx-btn-secondary" onClick={toggleMobileMenu}>
                <LogIn size={16} />
                Login
              </Link>
              <Link to="/signup" className="psx-btn psx-btn-primary" onClick={toggleMobileMenu}>
                <UserPlus size={16} />
                Sign Up
              </Link>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* App Store CTAs */}
      <div className="psx-header-ctas">
        <a href="#" className="psx-store-link" onClick={(e) => e.preventDefault()}>
          <Smartphone size={14} />
          App Store
        </a>
        <a href="#" className="psx-store-link" onClick={(e) => e.preventDefault()}>
          <Smartphone size={14} />
          Google Play
        </a>
      </div>
    </header>
  );
}