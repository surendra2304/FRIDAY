import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  basePath: "/friday",
  trailingSlash: true,
  turbopack: { root: process.cwd() },
};

export default nextConfig;
