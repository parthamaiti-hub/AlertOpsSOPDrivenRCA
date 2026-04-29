import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AIOps Alert Analytics with SOP-driven RCA",
  description: "Process Alerts by mapping SOP and determine RCA using AI Agents",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen" suppressHydrationWarning>
        <header className="bg-[#032147] text-white px-6 py-4">
          <a href="/" className="inline-flex items-center gap-3 group">
            <svg width="36" height="36" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <path d="M18 3L31 8.5V18C31 25 25 30.5 18 33C11 30.5 5 25 5 18V8.5L18 3Z" fill="#ecad0a" />
              <polyline points="8,18 12,18 14,12 17,24 20,14 22,18 28,18" fill="none" stroke="#032147" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-xl font-bold tracking-wide group-hover:text-[#ecad0a] transition-colors">
              AIOps Alert Analytics with SOP-driven RCA
            </span>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <circle cx="12" cy="12" r="10" stroke="#209dd7" strokeWidth="1.6" fill="#032147" />
              <ellipse cx="12" cy="12" rx="4.2" ry="10" stroke="#209dd7" strokeWidth="1.2" fill="none" />
              <line x1="2" y1="12" x2="22" y2="12" stroke="#209dd7" strokeWidth="1.2" />
              <ellipse cx="12" cy="12" rx="10" ry="3.8" stroke="#209dd7" strokeWidth="1.2" fill="none" />
            </svg>
          </a>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
