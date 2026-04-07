export const BREAKPOINTS = {
  tablet: 768,
  desktop: 1200,
} as const;

export const getLayoutMetrics = (width: number, height: number = 900) => {
  const isDesktop = width >= BREAKPOINTS.desktop;
  const isTablet = width >= BREAKPOINTS.tablet;
  const isCompactHeight = height < 760;
  const isShortHeight = height < 680;

  if (isDesktop) {
    return {
      isDesktop,
      isTablet,
      isCompactHeight,
      isShortHeight,
      horizontalPadding: 40,
      contentMaxWidth: 860,
      formMaxWidth: 620,
      panelGap: isCompactHeight ? 16 : 22,
      heroLogoWidth: isCompactHeight ? 210 : 270,
      buttonMinHeight: isCompactHeight ? 62 : 72,
      titleFontSize: 26,
      bodyFontSize: 19,
    };
  }

  if (isTablet) {
    return {
      isDesktop,
      isTablet,
      isCompactHeight,
      isShortHeight,
      horizontalPadding: 28,
      contentMaxWidth: 700,
      formMaxWidth: 580,
      panelGap: isCompactHeight ? 14 : 20,
      heroLogoWidth: isCompactHeight ? 190 : 235,
      buttonMinHeight: isCompactHeight ? 60 : 68,
      titleFontSize: 25,
      bodyFontSize: 18,
    };
  }

  return {
    isDesktop,
    isTablet,
    isCompactHeight,
    isShortHeight,
    horizontalPadding: 20,
    contentMaxWidth: 560,
    formMaxWidth: 560,
    panelGap: isCompactHeight ? 12 : 16,
    heroLogoWidth: isCompactHeight ? 170 : 210,
    buttonMinHeight: isCompactHeight ? 56 : 64,
    titleFontSize: 23,
    bodyFontSize: 18,
  };
};
