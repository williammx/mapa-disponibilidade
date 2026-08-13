import { AccessSection } from "../components/landing/AccessSection";
import { AudienceSection } from "../components/landing/AudienceSection";
import { BeforeAfterSection } from "../components/landing/BeforeAfterSection";
import { ClientViewSection } from "../components/landing/ClientViewSection";
import { FaqSection } from "../components/landing/FaqSection";
import { FinalCtaSection } from "../components/landing/FinalCtaSection";
import { HeroSection } from "../components/landing/HeroSection";
import { HowItWorksSection } from "../components/landing/HowItWorksSection";
import { LandingNav } from "../components/landing/LandingNav";
import { PrecisionSection } from "../components/landing/PrecisionSection";
import { ProblemSection } from "../components/landing/ProblemSection";
import { SiteFooter } from "../components/landing/SiteFooter";
import { StatusStrip } from "../components/landing/StatusStrip";

export function LandingPage() {
  return (
    <div className="min-h-screen bg-[#060C10] text-[#E8F1EC]">
      <LandingNav />
      <main>
        <HeroSection />
        <StatusStrip />
        <ProblemSection />
        <HowItWorksSection />
        <BeforeAfterSection />
        <PrecisionSection />
        <AudienceSection />
        <AccessSection />
        <ClientViewSection />
        <FaqSection />
        <FinalCtaSection />
      </main>
      <SiteFooter />
    </div>
  );
}
