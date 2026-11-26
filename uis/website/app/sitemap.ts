import type { MetadataRoute } from "next";

const ROUTES = ["", "/menu", "/ubicaciones", "/nuestra-historia", "/reservas", "/contacto", "/brasa-points"];

export default function sitemap(): MetadataRoute.Sitemap {
  return ROUTES.map((path) => ({
    url: `https://brasaland.com${path}`,
    changeFrequency: path === "/menu" ? "weekly" : "monthly",
    priority: path === "" ? 1 : 0.7,
  }));
}
