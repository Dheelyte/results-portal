import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Produces a self-contained server bundle for the production image.
  output: "standalone",
  reactStrictMode: true,
  // The parent portal page is the lightest in the system (ARCHITECTURE.md §8.5);
  // keep the build honest about what ships.
  poweredByHeader: false,
};

export default nextConfig;
