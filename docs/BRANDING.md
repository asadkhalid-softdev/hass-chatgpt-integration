# Integration icon

ChatGPT Assist ships an original teal house-and-speech-bubble icon. It does not use
the official OpenAI or Home Assistant logos.

Home Assistant 2026.3 and later load custom-integration artwork directly from
`custom_components/chatgpt_assist/brand/`:

- `icon.png`: 256 × 256, RGBA PNG with transparency.
- `icon@2x.png`: 512 × 512, RGBA PNG with transparency.

The square icon also serves as the logo fallback; no duplicate logo or dark variant
is needed. Both sizes are cropped to the artwork bounds, centered on a square
transparent canvas, resampled with Lanczos and saved with lossless PNG optimization.
No manifest changes or external brands submission are required. Update through HACS,
restart Home Assistant, and refresh the browser to load it. Image caching can delay
display. HACS store views may have their own branding/cache behavior.

Requirements: [Home Assistant integration brands and images](https://contributors.home-assistant.io/core/integrations/brands/).

## Artwork provenance

Generated with the built-in Imagegen tool on October 25, 2026. Final generation prompt:

> Create one original polished app integration icon for an independent open-source project called ChatGPT Assist that connects a conversational AI to Home Assistant. No text or letters. A single compact bold teal/cyan symbol merging a simple house roof silhouette with a rounded speech bubble and three simple conversational dots, visually coherent and distinctive rather than a collage. Clear at 24 pixels. Flat vector-like filled shapes, crisp smooth edges, strong mid-tone saturated teal/cyan that remains visible on white and charcoal backgrounds. No official OpenAI knot logo or Home Assistant logo, no trademarks, no gradients, no shadows, no border, no square background tile. Truly transparent background. Center the single nearly square symbol and make it fill the canvas edge-to-edge with no decorative whitespace; square PNG composition suitable for 256x256 and 512x512 Home Assistant brand/icon.png assets.
