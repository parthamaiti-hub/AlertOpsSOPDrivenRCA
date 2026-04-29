import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  output: "export", // ignored by `next dev`; required for FastAPI static serving
  images: { unoptimized: true },
  // rewrites() is incompatible with output:export — only include in dev
  ...(isDev
    ? {
        async rewrites() {
          return [
            {
              source: "/api/:path*",
              destination: "http://localhost:8000/api/:path*",
            },
          ];
        },
      }
    : {}),
};

export default nextConfig;
