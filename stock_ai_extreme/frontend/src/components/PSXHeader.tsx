import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Search, Menu, X, Settings, Sun, Moon, Smartphone, LogIn, UserPlus } from 'lucide-react';

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
    { path: '/market', label: 'Market' },
    { path: '/charts', label: 'Charts' },
    { path: '/forex-commodities', label: 'Forex & Commodities' },
    { path: '/sentiment', label: 'Sentiment' },
    { path: '/forecasts', label: 'Forecasts' },
    { path: '/announcements', label: 'Announcements' },
    { path: '/news', label: 'News' },
    { path: '/watchlist', label: 'Watchlist' },
    { path: '/popular', label: 'Popular' },
    { path: '/portfolio/transactions', label: 'Portfolio' },
  ];

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
              {link.label}
            </Link>
          ))}
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

      {/* Mobile Menu */}
      {isMobileMenuOpen && (
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
        </div>
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