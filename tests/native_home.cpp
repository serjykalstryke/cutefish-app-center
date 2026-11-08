#define main cutefish_app_center_program_main
#include "../src/main.cpp"
#undef main
#include <cassert>
#include <cmath>
#include <ui/test_input.h>
#include <ui/keys.h>

template<class T> static T* findView(ui::View* root,std::function<bool(T*)> match){
    if(auto* view=dynamic_cast<T*>(root);view && match(view))return view;
    for(auto& child:root->children())if(auto* found=findView<T>(child.get(),match))return found;
    return nullptr;
}
static ui::Label* text(ui::View* root,const std::string& value){return findView<ui::Label>(root,[&](auto* label){return label->text()==value;});}
static void click(ui::Window& window,ui::View* view){
    assert(view);for(auto* parent=view->parent();parent;parent=parent->parent())if(auto* scroll=dynamic_cast<ui::ScrollView*>(parent)){
        auto point=view->mapToWindow({0,0});auto origin=scroll->contentView()->mapToWindow({0,0});scroll->ensureVisible({point.x-origin.x,point.y-origin.y,view->geometry().width,view->geometry().height});
    }
    window.grab();ui::TestInput::click(window,view->mapToWindow({view->geometry().width/2,view->geometry().height/2}));
}

static void checkGlyph(ui::View* parent){
    auto* glyph=findView<ui::Icon>(parent,[](auto*){return true;});assert(glyph);
    auto pixels=glyph->grab(1);assert(!pixels.isNull());
    const auto color=ui::Theme::current().text;
    int visible=0;
    for(int y=0;y<pixels.height();y++)for(int x=0;x<pixels.width();x++){
        auto pixel=pixels.pixel(x,y);int alpha=pixel>>24;
        if(alpha<200)continue;
        // Bitmap channels are premultiplied. Check actual rendered ink, not
        // just the selected palette or the existence of a registered name.
        assert(std::abs(int((pixel>>16)&255)-color.r*alpha/255)<=3);
        assert(std::abs(int((pixel>>8)&255)-color.g*alpha/255)<=3);
        assert(std::abs(int(pixel&255)-color.b*alpha/255)<=3);
        visible++;
    }
    assert(visible>=pixels.width()/2);
}

static void checkThemeIcons(ui::Window& window,const std::string& page,int categories,bool filePage){
    const auto original=ui::Theme::current();
    auto* root=window.contentView();
    // Switch the same live view twice, exercising glyph-cache recoloring.
    for(const auto& theme:{ui::Theme::light(),ui::Theme::dark(),ui::Theme::light()}){
        ui::Theme::setCurrent(theme);window.grab();
        int navigationCount=0,categoryCount=0,dropCount=0;
        std::function<void(ui::View*)> visit=[&](ui::View* view){
            if(dynamic_cast<NavigationItem*>(view)){checkGlyph(view);navigationCount++;}
            if(dynamic_cast<CategoryTile*>(view)){checkGlyph(view);categoryCount++;}
            if(dynamic_cast<DropPanel*>(view)){checkGlyph(view);dropCount++;}
            for(auto& child:view->children())visit(child.get());
        };
        visit(root);assert(navigationCount==4);assert(categoryCount==categories);assert(dropCount==int(filePage));
        assert(window.grab().savePng("work/home-fixture/"+page+(theme.darkMode?"-dark.png":"-light.png")));
    }
    ui::Theme::setCurrent(original);window.grab();
}
int main(int argc,char** argv){
    const bool live=argc>1 && std::string(argv[1])=="--live";
    std::filesystem::create_directories("outputs");std::filesystem::create_directories("work/home-fixture");
    if(!live){
        auto backend=(std::filesystem::path(__FILE__).parent_path()/"details_fixture.py").string();setenv("CUTEFISH_APP_CENTER_BACKEND",backend.c_str(),1);
        auto folder=std::filesystem::absolute("work/home-fixture").string();setenv("APP_CENTER_DETAILS_FIXTURE_DIR",folder.c_str(),1);
    }
    ui::Application app(argc,argv,ui::Application::Platform::Headless);AppCenter center(app,false);center.show();auto& window=center.window();window.grab();
    assert(app.mainMenu());assert(app.mainMenu()->submenu(0)->role()==ui::MenuRole::Application);
    auto back=[&]{return findView<ui::Button>(window.contentView(),[](auto* button){return button->toolTip()=="Back to App Catalog";});};
    auto search=[&]{return findView<ui::SearchField>(window.contentView(),[](auto*){return true;});};
    auto source=[&]{return findView<ui::ComboBox>(window.contentView(),[](auto* combo){return combo->items().size()==5 && combo->items()[0]=="All sources";});};
    base::Timer poll(&app.loop());int stage=0,ticks=0,readyTicks=0,returnedAt=0;
    poll.onTimeout=[&]{
        if(++ticks>250){std::cerr<<"Timed out at home stage "<<stage<<"\n";app.quit(1);return;}
        window.grab();auto* root=window.contentView();
        if(stage==0 && text(root,"Firefox") && text(root,"LibreOffice") && text(root,"VLC")){
            if(++readyTicks<4)return;
            assert(text(root,"Catalog"));assert(text(root,"App Catalog"));assert(!text(root,"Discover"));assert(back() && !back()->isVisible());
            assert(text(root,"Explore categories"));assert(text(root,"1 / 2"));assert(!text(root,"Your software,\nin one place."));assert(!text(root,"Choose your source"));
            assert(findView<CategoryTile>(root,[](auto*){return true;}));assert(findView<FeaturedCard>(root,[](auto*){return true;}));
            checkThemeIcons(window,"discover",8,false);
            assert(window.grab().savePng(live?"outputs/app-center-discover.png":"work/home-fixture/discover.png"));
            auto* next=findView<ui::Button>(root,[](auto* button){return button->toolTip()=="Next featured apps";});click(window,next);stage=1;
        } else if(stage==1 && text(root,"Krita") && text(root,"2 / 2")){
            click(window,text(root,"About"));stage=2;
        } else if(stage==2 && text(root,"Created by")){
            assert(text(root,"David Stinnett"));assert(text(root,"Cutefish App Center"));assert(text(root,std::string("Version ")+APP_CENTER_VERSION));
            assert(!findView<FeaturedCard>(root,[](auto*){return true;}));
            assert(window.grab().savePng(live?"outputs/app-center-about.png":"work/home-fixture/about.png"));
            click(window,text(root,"Install from File"));stage=3;
        } else if(stage==3 && text(root,"Drop a package here")){
            assert(text(root,"Choose File…"));assert(!text(root,"Created by"));assert(findView<DropPanel>(root,[](auto*){return true;}));
            checkThemeIcons(window,"install",0,true);
            assert(window.grab().savePng(live?"outputs/app-center-install.png":"work/home-fixture/install.png"));
            if(live){std::cout<<"Live featured catalog, carousel, About credit and local-file page rendered.\n";app.quit();return;}
            auto* drop=findView<ui::FileDropArea>(root,[](auto*){return true;});drop->onDropped({"file:///tmp/Example%20Package.deb"});stage=4;
        } else if(stage==4 && text(root,"Example Package") && text(root,"Install")){
            assert(text(root,"Selected file"));assert(text(root,"Example Package.deb"));assert(!findView<FeaturedCard>(root,[](auto*){return true;}));
            click(window,text(root,"Catalog"));stage=5;
        } else if(stage==5 && text(root,"Featured apps") && text(root,"Explore categories")){
            assert(!text(root,"Example Package"));assert(!text(root,"Choose your source"));click(window,text(root,"Internet"));stage=6;
        } else if(stage==6 && text(root,"Example Team") && !text(root,"Loading app details…") && back()->isEnabled()){
            assert(search()->text()=="internet");assert(text(root,"Internet"));assert(!text(root,"App Catalog"));assert(text(root,"Open"));assert(back()->isVisible() && back()->isEnabled());
            assert(window.grab().savePng("work/home-fixture/category.png"));
            source()->setCurrentIndex(3);source()->onActivated(3);stage=7;
        } else if(stage==7 && text(root,"Example Team") && !text(root,"Loading app details…") && back()->isEnabled()){
            assert(text(root,"Internet"));assert(source()->currentIndex()==3);
            click(window,text(root,"Reload"));stage=8;
        } else if(stage==8 && text(root,"Example Team") && !text(root,"Loading app details…") && back()->isEnabled()){
            assert(text(root,"Internet"));search()->setText("example");search()->onTextEdited();stage=9;
        } else if(stage==9 && text(root,"Search Results") && text(root,"Example Team") && !text(root,"Loading app details…") && back()->isEnabled()){
            assert(!text(root,"Internet"));click(window,back());stage=10;
        } else if(stage==10 && text(root,"App Catalog") && text(root,"Explore categories")){
            assert(search()->text().empty());assert(source()->currentIndex()==0);assert(!back()->isVisible());assert(!text(root,"Example Team"));
            click(window,findView<FeaturedCard>(root,[](auto*){return true;}));stage=11;
        } else if(stage==11 && text(root,"Search Results") && text(root,"Example Team") && !text(root,"Loading app details…") && back()->isEnabled()){
            click(window,back());stage=12;
        } else if(stage==12 && text(root,"App Catalog")){
            click(window,text(root,"Audio & Video"));stage=13;
        } else if(stage==13 && text(root,"Example Team") && !text(root,"Loading app details…") && back()->isEnabled()){
            assert(text(root,"Audio & Video"));assert(search()->text()=="audio video");
            ui::TestInput::setKeyboardFocus(window,true);ui::TestInput::typeKey(window,ui::key::Left,ui::AltModifier);stage=14;
        } else if(stage==14 && text(root,"App Catalog")){
            assert(!back()->isVisible());search()->setText("example");search()->onAccepted();stage=15;
        } else if(stage==15 && text(root,"Search Results") && text(root,"Example Team") && !text(root,"Loading app details…") && back()->isEnabled()){
            search()->setText("pending");search()->onTextEdited();click(window,back());returnedAt=ticks;stage=16;
        } else if(stage==16 && ticks-returnedAt>=8){
            assert(text(root,"App Catalog"));assert(text(root,"Explore categories"));assert(search()->text().empty());assert(!text(root,"Search Results"));assert(!back()->isVisible());
            std::cout<<"Catalog naming, category headings, source/reload preservation, featured and typed searches, Back/Alt+Left, debounce cancellation, file review and theme switching passed.\n";app.quit();
        }
    };
    poll.start(100ms);return app.run();
}
