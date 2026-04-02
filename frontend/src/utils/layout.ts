export const BREAKPOINTS = {
  tablet: 768,
  desktop: 1200,
} as const;

export const getLayoutMetrics = (width: number) => {
  if (width >= BREAKPOINTS.desktop) {
    return {
      horizontalPadding: 36,
      contentMaxWidth: 760,
    };
  }

  if (width >= BREAKPOINTS.tablet) {
    return {
      horizontalPadding: 28,
      contentMaxWidth: 680,
    };
  }

  return {
    horizontalPadding: 20,
    contentMaxWidth: 560,
  };
};
