# End-to-End Figure Generation via the MATLAB MCP Server: A Random-Coefficient Quintic

**Date:** 12 Oct 2026 · **Host:** Windows 11 · **Orchestration:** Hermes Agent → `matlab-mcp-unofficial` MCP server

---

## 1. Objective

Demonstrate a complete, headless MATLAB figure-generation pipeline through the MATLAB MCP server: author an m-script outside MATLAB, upload it to the server's sandbox, execute it in batch mode, retrieve the rendered figure, and verify the result through independent channels — with no MATLAB GUI session at any point.

## 2. Environment

| Item | Value |
|---|---|
| MATLAB | R2024a (24.1.0.2837808, Update 7), PCWIN64 |
| Install path | `C:\Program Files\MATLAB\R2024a` |
| MCP server | `matlab-mcp-unofficial` (batch execution; file upload/download against a sandbox directory) |
| Sandbox | `C:\Users\MATTIA\AppData\Local\hermes\cache\scratch\matlab-sandbox` |
| Host OS | Windows 11 |

Environment access was confirmed up front with `matlab_info` before any code was sent.

## 3. Method

### 3.1 The m-script

`random_quintic_plot.m` (1,031 bytes) proceeds as follows:

1. **Coefficient draw.** `c = (2*rand(1,6) - 1) * 5` — six i.i.d. coefficients, each uniform on [−5, 5], taken as the coefficients of a degree-5 polynomial in descending powers of *x*.
2. **Sampling.** `x = linspace(-2, 2, 400)`; evaluation via `polyval(c, x)`.
3. **Rendering.** A headless figure (`figure('Visible','off')`) with grid, dashed zero-lines at *x* = 0 and *y* = 0, and a title that auto-formats the polynomial through a local function (`%+.4g` per term).
4. **Export.** `print(gcf, 'random_quintic_plot.png', '-dpng', '-r150')`.

Full source in Appendix A.

### 3.2 Workflow

| Step | Channel | Result |
|---|---|---|
| 1 | `matlab_info` | version/platform confirmed |
| 2 | local authoring → base64 → `matlab_upload_file` | script in sandbox |
| 3 | `matlab_run_script('random_quintic_plot.m')` | batch execution |
| 4 | `matlab_download_file('random_quintic_plot.png')` → base64 → local decode | PNG on disk |
| 5 | verification (Section 4) | three independent channels |

## 4. Results

### 4.1 Execution

- Exit code 0; empty stdout and stderr.
- Artifact: valid PNG, 875 × 656 px, 8-bit RGB, 26,478 bytes. Embedded tEXt metadata confirms provenance: `Software: MATLAB, The MathWorks, Inc.`, `Creation Time: 12-Oct-2026 14:54:16`.

### 4.2 Identification of the plotted polynomial

Two independent channels identify the coefficients:

- **Channel A (MATLAB stdout).** A separate batch execution of the same draw expression printed
  `3.1472  4.0579  -3.7301  4.1338  1.3236  -4.0246`.
- **Channel B (optical read of the rendered figure).** The figure title was read as
  `p(x) = 3.147x⁵ + 4.058x⁴ − 3.73x³ + 4.134x² + 1.324x − 4.025` (4 significant figures).

The channels agree at every digit the title's resolution allows, so the plotted polynomial is

> **p(x) = 3.1472x⁵ + 4.0579x⁴ − 3.7301x³ + 4.1338x² + 1.3236x − 4.0246**

The agreement is not coincidental: it is explained by Finding 3 below (shared default RNG state across batch invocations).

### 4.3 Shape verification: figure read vs. analytic computation

A third batch execution computed roots and critical points directly (`roots`, `polyder`); each quantity read off the figure is compared:

| Quantity | Read from figure | Computed | Agreement |
|---|---|---|---|
| Local maximum | ≈ +13–14 at *x* ≈ −1.6 | *x* = −1.6409, *p* = 13.3936 | ✓ |
| Local minimum | ≈ −4–5 at *x* ≈ −0.2 | *x* = −0.1324, *p* = −4.1176 | ✓ |
| Negative real root | ≈ −0.85 | −0.7928 | ✓ |
| Positive real root | ≈ 0.75 | 0.7685 | ✓ |
| Left endpoint | ≈ +5 | *p*(−2) = 3.9202 | ✓ |
| Right endpoint | ≈ +150 | *p*(2) = 150.9538 | ✓ |

The remaining two roots form the complex-conjugate pair 0.3957 ± 0.9296i, consistent with the shallow central dip. A third real root, −2.0564, lies just outside the plotted window — consistent with the curve being slightly positive at *x* = −2. All six read values are confirmed by direct computation.

## 5. Findings

1. **Headless figure generation works end-to-end.** `figure('Visible','off')` + `print` yields a clean PNG in pure batch mode; the upload → execute → download round-trip requires no GUI and no display server.
2. **The base64 envelope inflates payloads by 4/3.** A 26.5 kB figure arrived as 70.9 kB of base64 text. The agent runtime handled it via disk spillover, but larger artifacts (high-DPI or multi-page exports) will stress context limits — plan for spillover handling or chunked retrieval.
3. **Batch-mode RNG state is shared across invocations.** Each `matlab -batch` process starts from the same default RNG state, so a "random" draw reproduces *exactly* in every fresh invocation (this is why Channels A and B agree). As written, the experiment is **reproducible, not random**: genuinely different coefficients per run require `rng('shuffle')` (or an explicit seed, for controlled reproducibility).
4. **Multi-channel verification is cheap and effective.** Structural (PNG header/metadata), numerical (cross-channel coefficient agreement), and analytic (figure read vs. roots/critical points) checks together give high confidence in the artifact with no human in the loop.

## 6. Limitations

- Verification relied on optical reading plus analytic cross-check; no pixel-diff against a reference render was performed.
- The script does not log its own coefficients; Channel A was recovered by re-executing the draw expression. Adding `disp(c)` (or a sidecar file) would make the artifact self-describing.
- Single-platform observation (PCWIN64, R2024a); the default-RNG-state behavior has not been tested on other releases or platforms.

---

## Appendix A: `random_quintic_plot.m`

```matlab
% random_quintic_plot.m
% Plot a quintic polynomial with random coefficients.

c = (2*rand(1,6) - 1) * 5;      % coeffs of x^5, x^4, ..., x, 1  in [-5, 5]
x = linspace(-2, 2, 400);
y = polyval(c, x);

figure('Visible', 'off');
plot(x, y, 'LineWidth', 2, 'Color', [0.15 0.45 0.85]);
grid on;
xlabel('x');
ylabel('p(x)');
title(sprintf('p(x) = %s', polyToString(c)));
hold on;
xline(0, 'k--', 'LineWidth', 0.5);
yline(0, 'k--', 'LineWidth', 0.5);
hold off;

print(gcf, 'random_quintic_plot.png', '-dpng', '-r150');
close(gcf);

function s = polyToString(c)
%POLYTOSTRING Build a "5.31x^5 - 2.10x^4 + ..." style string from coeffs.
    powers = (numel(c)-1):-1:0;
    terms = cell(1, numel(c));
    for k = 1:numel(c)
        p = powers(k);
        if p == 0
            xpart = '';
        elseif p == 1
            xpart = 'x';
        else
            xpart = sprintf('x^%d', p);
        end
        terms{k} = sprintf('%+.4g%s', c(k), xpart);
    end
    s = strjoin(terms, ' ');
    if s(1) == '+'
        s(1) = [];
    end
end
```

## Appendix B: Verification commands and output

```matlab
c = [3.1472 4.0579 -3.7301 4.1338 1.3236 -4.0246];
r = roots(c)
%  -2.0564 + 0.0000i
%  -0.7928 + 0.0000i
%   0.3957 + 0.9296i
%   0.3957 - 0.9296i
%   0.7685 + 0.0000i

crit = roots(polyder(c));          % real critical points: -1.6409, -0.1324
polyval(c, [-1.6409, -0.1324])     %  13.3936, -4.1176
polyval(c, [-2, 2])                %   3.9202, 150.9538
```

## Appendix C: Artifact

`random_quintic_plot.png` — 875 × 656 px, 8-bit RGB, 26,478 bytes, 150 dpi export (creation 12-Oct-2026 14:54:16).
