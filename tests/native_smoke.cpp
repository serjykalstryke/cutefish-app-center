#define main cutefish_app_center_program_main
#include "../src/main.cpp"
#undef main
#include <cassert>
#include <ui/test_input.h>
#include <ui/keys.h>

static ui::Label* findLabel(ui::View* v,const std::string& text) {
    if(auto* l=dynamic_cast<ui::Label*>(v);l && l->text()==text)return l;
    for(auto& c:v->children())if(auto* l=findLabel(c.get(),text))return l;
    return nullptr;
}
static bool containsLabel(ui::View* v,const std::string& text) {
    if(auto* l=dynamic_cast<ui::Label*>(v);l && l->text().find(text)!=std::string::npos)return true;
    for(auto& c:v->children())if(containsLabel(c.get(),text))return true;
    return false;
}
static ui::SearchField* findSearch(ui::View* v) {
    if(auto* s=dynamic_cast<ui::SearchField*>(v))return s;
    for(auto& c:v->children())if(auto* s=findSearch(c.get()))return s;
    return nullptr;
}
static void click(ui::Window& w,ui::View* v) {
    assert(v);auto point=v->mapToWindow({v->geometry().width/2,v->geometry().height/2});ui::TestInput::click(w,point);
}
int main(int argc,char** argv) {
    ui::Application app(argc,argv,ui::Application::Platform::Headless);
    AppCenter store(app,false);store.show();auto& w=store.window();
    w.grab();assert(app.mainMenu());assert(app.mainMenu()->submenu(0)->role()==ui::MenuRole::Application);
    click(w,findLabel(w.contentView(),"Installed"));
    base::Timer poll(&app.loop());int stage=0,ticks=0;
    poll.onTimeout=[&] {
        if(++ticks>200){std::cerr<<"Timed out waiting for native UI\n";app.quit(1);return;}
        w.grab();
        bool ready=containsLabel(w.contentView()," entries");
        if(stage==0 && ready){
            assert(findLabel(w.contentView(),"Installed"));assert(!findLabel(w.contentView(),"Updates"));
            std::function<ui::ComboBox*(ui::View*)> filter=[&](ui::View* view)->ui::ComboBox*{
                if(auto* combo=dynamic_cast<ui::ComboBox*>(view);combo && !combo->items().empty() && combo->items()[0]=="Applications")return combo;
                for(auto& child:view->children())if(auto* found=filter(child.get()))return found;
                return nullptr;
            };
            auto* view=filter(w.contentView());assert(view);view->setCurrentIndex(1);view->onActivated(1);
            auto* search=findSearch(w.contentView());click(w,search);ui::TestInput::setKeyboardFocus(w,true);ui::TestInput::typeText(w,"snapd");stage=1;
        } else if(stage==1 && ready && containsLabel(w.contentView(),"snapd") && !containsLabel(w.contentView(),"300 entries")) {
            w.grab().savePng("work/installed-smoke.png");
            click(w,findLabel(w.contentView(),"Discover"));w.grab();
            assert(findLabel(w.contentView(),"Explore categories"));
            click(w,findLabel(w.contentView(),"Internet"));stage=2;
        } else if(stage==2 && containsLabel(w.contentView(),"best matches first")) {
            assert(findSearch(w.contentView())->text()=="internet");
            assert(findLabel(w.contentView(),"Brave"));
            assert(findLabel(w.contentView(),"Google Chrome"));
            assert(findLabel(w.contentView(),"Firefox"));
            assert(!findLabel(w.contentView(),"chromium-sandbox"));
            w.grab().savePng("work/search-smoke.png");
            std::cout<<"Native controls, async inventory, category search, and navigation passed.\n";app.quit();
        }
    };
    poll.start(100ms);return app.run();
}
