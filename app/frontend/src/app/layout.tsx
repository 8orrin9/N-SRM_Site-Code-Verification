import type { Metadata } from "next";
import "./globals.css";
import Nav from "@/components/Nav";
import Toaster from "@/components/Toaster";

export const metadata: Metadata = {
  title: "N-SRM · Site 표준화/중복/유사 검색",
  description: "Site 코드 표준화·실재검증·중복제거·유사검색 서비스",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <header className="gnb">
          <div className="gnb-top">
            <div className="brand">
              <span className="samsung-mark">SAMSUNG</span>
              <span className="nsrm-logo"><span className="nsrm-mark">DS N-SRM</span></span>
            </div>
          </div>
          <Nav />
        </header>
        <main>{children}</main>
        <Toaster />
      </body>
    </html>
  );
}
