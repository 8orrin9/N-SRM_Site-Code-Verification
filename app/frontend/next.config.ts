import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "export",
  trailingSlash: true,             // export를 out/<route>/index.html 구조로 생성 → 직접 접근·새로고침 시 정적 서빙 가능
  images: { unoptimized: true },   // export 시 이미지 최적화 서버 불가
};

export default nextConfig;
