export const BREAKPOINTS = {
  mobile: 480,
  mobileLarge: 768,
  tablet: 1024,
} as const;

export const getLayoutMetrics = (width: number, height: number = 900) => {
  const isMobile = width <= BREAKPOINTS.mobile;
  const isMobileLarge = width > BREAKPOINTS.mobile && width <= BREAKPOINTS.mobileLarge;
  const isTablet = width > BREAKPOINTS.mobileLarge && width <= BREAKPOINTS.tablet;
  const isDesktop = width > BREAKPOINTS.tablet;
  const isHandset = width <= BREAKPOINTS.mobileLarge;
  const isCompactHeight = height < 760;
  const isShortHeight = height < 680;

  if (isDesktop) {
    return {
      isMobile,
      isMobileLarge,
      isTablet,
      isDesktop,
      isHandset,
      isCompactHeight,
      isShortHeight,
      horizontalPadding: 40,
      contentMaxWidth: 980,
      formMaxWidth: 660,
      panelGap: isCompactHeight ? 16 : 22,
      heroLogoWidth: isCompactHeight ? 220 : 300,
      buttonMinHeight: isCompactHeight ? 62 : 72,
      titleFontSize: 28,
      bodyFontSize: 19,
    };
  }

  if (isTablet) {
    return {
      isMobile,
      isMobileLarge,
      isTablet,
      isDesktop,
      isHandset,
      isCompactHeight,
      isShortHeight,
      horizontalPadding: 30,
      contentMaxWidth: 820,
      formMaxWidth: 620,
      panelGap: isCompactHeight ? 14 : 20,
      heroLogoWidth: isCompactHeight ? 210 : 270,
      buttonMinHeight: isCompactHeight ? 60 : 68,
      titleFontSize: 26,
      bodyFontSize: 18,
    };
  }

  if (isMobileLarge) {
    return {
      isMobile,
      isMobileLarge,
      isTablet,
      isDesktop,
      isHandset,
      isCompactHeight,
      isShortHeight,
      horizontalPadding: 18,
      contentMaxWidth: 640,
      formMaxWidth: 500,
      panelGap: isCompactHeight ? 10 : 14,
      heroLogoWidth: isCompactHeight ? 168 : 204,
      buttonMinHeight: isCompactHeight ? 52 : 58,
      titleFontSize: 24,
      bodyFontSize: 16,
    };
  }

  return {
    isMobile,
    isMobileLarge,
    isTablet,
    isDesktop,
    isHandset,
    isCompactHeight,
    isShortHeight,
    horizontalPadding: 14,
    contentMaxWidth: 400,
    formMaxWidth: 400,
    panelGap: isCompactHeight ? 8 : 12,
    heroLogoWidth: isCompactHeight ? 136 : 168,
    buttonMinHeight: isCompactHeight ? 50 : 56,
    titleFontSize: 21,
    bodyFontSize: 15,
  };
};
