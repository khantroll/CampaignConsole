---
name: Obsidian Terminal
colors:
  surface: '#041426'
  surface-dim: '#041426'
  surface-bright: '#2b3a4d'
  surface-container-lowest: '#000f20'
  surface-container-low: '#0c1c2e'
  surface-container: '#102032'
  surface-container-high: '#1b2b3d'
  surface-container-highest: '#263649'
  on-surface: '#d4e4fc'
  on-surface-variant: '#bac9cc'
  inverse-surface: '#d4e4fc'
  inverse-on-surface: '#223144'
  outline: '#849396'
  outline-variant: '#3b494c'
  surface-tint: '#00daf3'
  primary: '#c3f5ff'
  on-primary: '#00363d'
  primary-container: '#00e5ff'
  on-primary-container: '#00626e'
  inverse-primary: '#006875'
  secondary: '#b1cad7'
  on-secondary: '#1c333e'
  secondary-container: '#334a55'
  on-secondary-container: '#a0b9c5'
  tertiary: '#ffeac0'
  on-tertiary: '#3e2e00'
  tertiary-container: '#fec931'
  on-tertiary-container: '#6f5500'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#9cf0ff'
  primary-fixed-dim: '#00daf3'
  on-primary-fixed: '#001f24'
  on-primary-fixed-variant: '#004f58'
  secondary-fixed: '#cde6f4'
  secondary-fixed-dim: '#b1cad7'
  on-secondary-fixed: '#051e28'
  on-secondary-fixed-variant: '#334a55'
  tertiary-fixed: '#ffdf96'
  tertiary-fixed-dim: '#f3bf26'
  on-tertiary-fixed: '#251a00'
  on-tertiary-fixed-variant: '#594400'
  background: '#041426'
  on-background: '#d4e4fc'
  surface-variant: '#263649'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 34px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 26px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.08em
  mono-data:
    fontFamily: monospace
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 16px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 4px
  gutter: 12px
  margin-mobile: 16px
  margin-desktop: 24px
  container-padding: 12px
---

## Brand & Style

The design system is a functional-industrial framework designed for high-density information management. It evokes the feeling of a tactical command station—utilitarian, precise, and authoritative. The target audience consists of power-users who prioritize data visibility and quick-action workflows over decorative whitespace.

The visual style is **Industrial / Modern**, leaning into visible structural components. It rejects the "floating" nature of modern minimalism in favor of anchored containers, hard edges, and clear semantic zoning. Every element serves a functional purpose, with a "Campaign Console" aesthetic that feels like a specialized piece of hardware.

**Key Principles:**
- **Information Density:** Content is packed tightly but organized through rigid structural alignment.
- **Systemic Clarity:** Status is communicated through a strict high-contrast color protocol (Minimal, Partial, Complete).
- **Tactical Utility:** Elements feature subtle bevels and inner borders to imply physical interaction and durability.

## Colors

The palette is rooted in a "Deep Space" dark mode, utilizing `#051424` as the primary background to reduce eye strain during long sessions while providing a high-contrast base for data.

- **Primary:** A neon cyan (`#00E5FF`) used sparingly for interactive highlights and focus states, acting as the "power on" indicator.
- **Surface Tiers:** Layering is achieved through varying shades of navy and charcoal. Backgrounds use the base hex, while cards and containers use a slightly lighter `#102032`.
- **Status Protocol:** This is the most critical color application:
  - **Minimal:** Vivid Red (`#FF5252`) for urgent attention or lack of data.
  - **Partial:** Amber (`#FFD740`) for work-in-progress.
  - **Complete:** Emerald (`#69F0AE`) for finalized entries.
- **Accents:** Muted grays and blues are used for structural borders to keep the focus on the data, not the frame.

## Typography

This design system uses **Inter** exclusively for its exceptional legibility at small sizes and high-density environments. The type scale is compact, favoring clarity over elegance.

- **Headlines:** Use tight letter-spacing and heavy weights to create strong visual anchors for different console modules.
- **Data Labels:** The `label-caps` style is used for "meta-data" headers like "NPC", "LOCATION", or "STATUS", providing a clear distinction between the label and the user content.
- **Contextual Monospace:** For ID numbers, versioning (e.g., "3rd Edition"), or specific technical outputs, a fallback monospace font is used to reinforce the console aesthetic.
- **Mobile Scaling:** Large headers downscale by approximately 20% on mobile to prevent text wrapping in narrow columns, while body sizes remain at 14px for touch readability.

## Layout & Spacing

The layout follows a **Fluid Grid** model with high-density spacing. It uses a 12-column system on desktop that collapses to a single column on mobile.

- **Rhythm:** A 4px baseline grid ensures consistent alignment. Component padding is kept to a minimum (8px to 12px) to maximize the amount of visible data on screen.
- **Zoning:** Content is organized into "Modules" (e.g., Entity Overview, NPC List). Each module is a distinct container with a visible header.
- **Mobile Reflow:** On mobile, sidebars move to a bottom-docked navigation or a top-level accordion to keep the main console workspace clear. 
- **Density:** Gutters are narrowed to 12px to allow more horizontal space for data tables and multi-action button rows.

## Elevation & Depth

In this design system, depth is communicated through **Tonal Layering** and **Structural Outlines** rather than soft shadows.

- **Surface Tiers:** The base background is the deepest layer. Secondary containers (cards, sidebars) sit on top, distinguished by a subtle 1px border (`#1A2C3E`) and a slightly lighter fill.
- **Inset Effects:** Input fields and secondary action areas use an "inset" look—darker backgrounds with a subtle top-inner-shadow—to suggest they are carved into the console.
- **Active Focus:** Hovering over an interactive element doesn't lift it; instead, it triggers a "Glow" effect (a 0px blur, 2px stroke of the primary color) to simulate a digital screen highlight.
- **Separators:** Horizontal and vertical rules are low-contrast, acting as subtle "seams" in the interface.

## Shapes

The shape language is **Soft (0.25rem)**. This provides a balance between the "hard" industrial feel and modern digital usability.

- **Containers:** Standard modules and cards use `rounded-sm` (4px).
- **Interactive Elements:** Buttons and tags use a consistent 4px radius. 
- **Status Indicators:** Progress bars and status chips use the same 4px radius to maintain a unified structural language.
- **Strictness:** Avoid using pill shapes or circles, except for specific avatar icons or circular status pips, to maintain the architectural, grid-based aesthetic.

## Components

- **Buttons:** Compact height (32px default). Primary buttons use a solid fill; secondary buttons use a ghost style with a visible border. Destructive actions (Delete) use the `status_minimal` red border.
- **Status Chips:** High-contrast background with bold white or black text. They are the primary way to communicate completeness at a glance.
- **Progress Bars:** Thin (4px - 6px) indicators placed directly under headers or labels. They use the status color protocol (Red/Amber/Green).
- **Data Cards:** These are the workhorses of the system. They feature a rigid header area for labels and icons, a body area for descriptions, and a footer area for metadata and quick-actions.
- **Quick-Action Buttons:** Small icon-only or short-text buttons (e.g., "Edit", "Sync") grouped in the top-right of cards to keep them accessible without cluttering the data field.
- **Input Fields:** Dark background with a prominent focus border. No labels outside the field; use high-contrast placeholder text or inline labels to save vertical space.