"use client";

/**
 * The frame every signed-in staff screen sits in (ARCHITECTURE.md §3, §8).
 *
 * One sidebar, one header, three roles. The sidebar collapses to an icon
 * rail on a wide screen and becomes a drawer below `lg`, because §8.1 and
 * §8.3 both assume a teacher on their own phone: a permanent 16rem column
 * would leave a 360px-wide screen with 100px for a thirty-pupil sheet.
 *
 * The collapsed/expanded choice is remembered in `localStorage`, which is the
 * right place for it — it is a per-browser convenience, not state the server
 * has any business knowing, and a read that throws in a private window just
 * leaves the sidebar expanded.
 *
 * The parent's pages do **not** use this. They are server-rendered under
 * §8.5's 150 KB budget and carry no client JavaScript at all; their own
 * header is in `app/(parent)/layout.tsx` (docs/DECISIONS.md D89, D103).
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  ChevronLeft,
  ChevronRight,
  LogOut,
  Menu,
  X,
  type LucideIcon,
} from "lucide-react";

import { Avatar, Button, Crest } from "@/components/ui";
import type { NavSection } from "@/components/shell/nav";
import { isActive } from "@/lib/nav-active";

const COLLAPSED_KEY = "sshms_sidebar_collapsed";

const SCHOOL = "Self-Starters House Montessori School";

export function AppShell({
  navLabel,
  sections,
  area,
  areaHref,
  areaIcon: AreaIcon,
  user,
  roleLabel,
  onSignOut,
  children,
}: {
  /** The sidebar's accessible name, e.g. "Setup sections". */
  navLabel: string;
  sections: NavSection[];
  /** What this part of the portal is called, in the header. */
  area: string;
  areaHref: string;
  areaIcon: LucideIcon;
  user: { full_name: string };
  roleLabel: string;
  onSignOut: () => void;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawer = useRef<HTMLDivElement | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  // Read the remembered width after mount. Doing it in `useState`'s
  // initialiser would make the server's HTML and the client's first render
  // disagree whenever the two differ.
  useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(COLLAPSED_KEY) === "1");
    } catch {
      // Private window, or site data blocked. Expanded is the right default.
    }
  }, []);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
      } catch {
        // Not worth failing a click over.
      }
      return next;
    });
  }, []);

  // A drawer that survived the navigation it was opened to make would cover
  // the page that arrived — completely, because it is fixed over the whole
  // viewport.
  //
  // This handles the back button, and anything that navigates without a
  // click. It does **not** handle the tap on the link for the page you are
  // already on, because then the pathname never changes and this never
  // fires; the drawer's own links close it on click for that
  // (`navigation.spec.ts` found it).
  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  // Escape closes it, and while it is open the page behind does not scroll.
  useEffect(() => {
    if (!drawerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    drawer.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previous;
    };
  }, [drawerOpen]);

  const signOut = () => {
    setSigningOut(true);
    onSignOut();
  };

  const nav = (
    <SidebarNav
      label={navLabel}
      sections={sections}
      pathname={pathname}
      collapsed={collapsed}
    />
  );

  return (
    <div className="min-h-screen lg:flex">
      {/* ---------------- the rail, from `lg` up ---------------- */}
      <div
        className={`hidden shrink-0 border-r border-[var(--border)] bg-[var(--surface)] lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col ${
          collapsed ? "lg:w-[4.5rem]" : "lg:w-64"
        }`}
      >
        <div
          className={`flex items-center gap-2 border-b border-[var(--border)] px-3 py-4 ${
            collapsed ? "justify-center" : ""
          }`}
        >
          <Link
            href={areaHref}
            className="flex min-w-0 items-center gap-2.5"
            title={collapsed ? `${SCHOOL} — ${area}` : undefined}
          >
            <Crest />
            {collapsed ? null : (
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold leading-tight">
                  Results Portal
                </span>
                <span className="block truncate text-[0.7rem] text-[var(--muted)]">
                  {SCHOOL}
                </span>
              </span>
            )}
          </Link>
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-3">{nav}</div>

        <div className="border-t border-[var(--border)] p-2">
          <button
            type="button"
            onClick={toggleCollapsed}
            aria-expanded={!collapsed}
            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-xs text-[var(--muted)] transition hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)]"
          >
            {collapsed ? (
              <ChevronRight aria-hidden className="size-4 shrink-0" />
            ) : (
              <ChevronLeft aria-hidden className="size-4 shrink-0" />
            )}
            {collapsed ? <span className="sr-only">Expand the sidebar</span> : "Collapse"}
          </button>
        </div>
      </div>

      {/* ---------------- the drawer, below `lg` ---------------- */}
      {drawerOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close the menu"
            onClick={() => setDrawerOpen(false)}
            className="absolute inset-0 bg-black/50"
          />
          <div
            ref={drawer}
            role="dialog"
            aria-modal="true"
            aria-label="Menu"
            tabIndex={-1}
            className="absolute inset-y-0 left-0 flex w-[17rem] max-w-[85%] flex-col bg-[var(--surface)] shadow-xl outline-none"
          >
            <div className="flex items-center justify-between gap-2 border-b border-[var(--border)] px-3 py-3">
              <span className="flex min-w-0 items-center gap-2.5">
                <Crest />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold leading-tight">
                    Results Portal
                  </span>
                  <span className="block truncate text-[0.7rem] text-[var(--muted)]">
                    {area}
                  </span>
                </span>
              </span>
              <button
                type="button"
                onClick={() => setDrawerOpen(false)}
                className="rounded-lg p-2 text-[var(--muted)] hover:bg-[var(--surface-raised)]"
              >
                <X aria-hidden className="size-5" />
                <span className="sr-only">Close the menu</span>
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-2 py-3">
              <SidebarNav
                label={navLabel}
                sections={sections}
                pathname={pathname}
                collapsed={false}
                onNavigate={() => setDrawerOpen(false)}
              />
            </div>

            <div className="flex items-center gap-2 border-t border-[var(--border)] px-3 py-3">
              <Avatar name={user.full_name} size="sm" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{user.full_name}</span>
                <span className="block truncate text-xs text-[var(--muted)]">{roleLabel}</span>
              </span>
            </div>
          </div>
        </div>
      ) : null}

      {/* ---------------- the page ---------------- */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 border-b border-[var(--border)] bg-[var(--surface)]">
          <div className="flex items-center gap-3 px-4 py-2.5">
            <button
              type="button"
              onClick={() => setDrawerOpen(true)}
              aria-expanded={drawerOpen}
              className="rounded-lg border border-[var(--border)] p-2 text-[var(--muted)] transition hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)] lg:hidden"
            >
              <Menu aria-hidden className="size-5" />
              <span className="sr-only">Open the menu</span>
            </button>

            <div className="flex min-w-0 flex-1 items-center gap-2">
              <AreaIcon aria-hidden className="size-4 shrink-0 text-[var(--brand)]" />
              <span className="truncate text-sm font-semibold">{area}</span>
            </div>

            <div className="flex items-center gap-2">
              <span className="hidden min-w-0 text-right sm:block">
                <span className="block truncate text-sm font-medium leading-tight">
                  {user.full_name}
                </span>
                <span className="block truncate text-xs text-[var(--muted)]">{roleLabel}</span>
              </span>
              <Avatar name={user.full_name} />
              <Button
                variant="secondary"
                size="sm"
                icon={LogOut}
                loading={signingOut}
                onClick={signOut}
              >
                <span className="hidden sm:inline">Sign out</span>
                <span className="sr-only sm:hidden">Sign out</span>
              </Button>
            </div>
          </div>
        </header>

        <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-6">
          {children}
        </main>
      </div>
    </div>
  );
}

function SidebarNav({
  label,
  sections,
  pathname,
  collapsed,
  onNavigate,
}: {
  label: string;
  sections: NavSection[];
  pathname: string;
  collapsed: boolean;
  /** The drawer passes this so a tap closes it, even on the current page. */
  onNavigate?: () => void;
}) {
  return (
    <nav aria-label={label} className="flex flex-col gap-4">
      {sections.map((section, index) => (
        <div key={section.heading ?? `section-${index}`} className="flex flex-col gap-1">
          {section.heading && !collapsed ? (
            <p className="px-2.5 pb-0.5 text-[0.65rem] font-semibold uppercase tracking-wider text-[var(--muted)]">
              {section.heading}
            </p>
          ) : null}
          <ul className="flex flex-col gap-0.5">
            {section.items.map((item) => {
              const active = isActive(pathname, item.href, item.exact);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    title={collapsed ? item.label : undefined}
                    className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition ${
                      collapsed ? "justify-center" : ""
                    } ${
                      active
                        ? "bg-[var(--brand-soft)] font-semibold text-[var(--brand)]"
                        : "text-[var(--muted)] hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)]"
                    }`}
                  >
                    <item.icon aria-hidden className="size-4 shrink-0" />
                    {collapsed ? (
                      <span className="sr-only">{item.label}</span>
                    ) : (
                      <span className="truncate">{item.label}</span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
