import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";
const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  devIndicators: false,
  output: isDev ? undefined : "export",
  ...(isDev
    ? {
        async rewrites() {
          return [
            {
              source: "/api/:path*",
              destination: `${backendUrl}/api/:path*`,
            },
          ];
        },
      }
    : {}),
};

export default nextConfig;
