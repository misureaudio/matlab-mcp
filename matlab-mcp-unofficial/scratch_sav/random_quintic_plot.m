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
